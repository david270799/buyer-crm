"""In-memory Database with Firestore-like transaction semantics.

Used by the test-suite and for local experiments. It deliberately enforces
the same constraints as Firestore so that code passing here also works on
the real thing:

* reads after writes inside a transaction raise ReadAfterWriteError;
* commit is optimistic: if a document (or a queried collection) read by the
  transaction changed before commit, the function is re-run;
* create/update preconditions are checked at commit, atomically;
* only Firestore-storable value types are accepted.
"""

import copy
import threading
import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from crm.storage.base import (
    Doc,
    DocumentExistsError,
    DocumentMissingError,
    Filter,
    OrderBy,
    ReadAfterWriteError,
    T,
    Transaction,
    TransactionContentionError,
    run_callbacks,
)

_SCALARS = (type(None), bool, int, float, str, bytes, datetime)


def _check_storable(value: Any, path: str = "") -> None:
    if isinstance(value, _SCALARS):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_storable(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"Non-string key at {path!r}")
            _check_storable(item, f"{path}.{key}" if path else key)
        return
    raise TypeError(f"Firestore cannot store {type(value).__name__} at {path!r}")


def _matches(data: Doc, flt: Filter) -> bool:
    if flt.field not in data:
        return False
    value = data[flt.field]
    try:
        if flt.op == "==":
            return value == flt.value
        if flt.op == "!=":
            return value != flt.value
        if flt.op == "in":
            return value in flt.value
        if flt.op == "array_contains":
            return isinstance(value, list) and flt.value in value
        if flt.op == "<":
            return value < flt.value
        if flt.op == "<=":
            return value <= flt.value
        if flt.op == ">":
            return value > flt.value
        if flt.op == ">=":
            return value >= flt.value
    except TypeError:
        return False
    raise ValueError(f"Unsupported filter op {flt.op!r}")


class InMemoryDatabase:
    def __init__(self, max_attempts: int = 5):
        self._lock = threading.RLock()
        # collection -> doc_id -> (version, data)
        self._docs: dict[str, dict[str, tuple[int, Doc]]] = defaultdict(dict)
        self._collection_versions: dict[str, int] = defaultdict(int)
        self._next_version = 1
        self._max_attempts = max_attempts
        self.commit_count = 0

    # --- non-transactional reads ------------------------------------------

    def get(self, collection: str, doc_id: str) -> Doc | None:
        with self._lock:
            entry = self._docs[collection].get(doc_id)
            return copy.deepcopy(entry[1]) if entry else None

    def get_many(self, collection: str, doc_ids: Sequence[str]) -> dict[str, Doc | None]:
        return {doc_id: self.get(collection, doc_id) for doc_id in doc_ids}

    def query(
        self,
        collection: str,
        filters: Sequence[Filter] = (),
        order_by: OrderBy | None = None,
        limit: int | None = None,
    ) -> list[tuple[str, Doc]]:
        with self._lock:
            rows = [
                (doc_id, data)
                for doc_id, (_, data) in sorted(self._docs[collection].items())
                if all(_matches(data, flt) for flt in filters)
            ]
            if order_by is not None:
                # Like Firestore: documents without the ordered field are excluded.
                rows = [row for row in rows if order_by.field in row[1]]
                rows.sort(key=lambda row: row[1][order_by.field], reverse=order_by.descending)
            if limit is not None:
                rows = rows[:limit]
            # Copy only what is returned: callers may modify their copies.
            return [(doc_id, copy.deepcopy(data)) for doc_id, data in rows]

    def scan(self, collection: str) -> list[tuple[str, Doc]]:
        return self.query(collection)

    def list_ids(self, collection: str) -> list[str]:
        with self._lock:
            return sorted(self._docs[collection])

    def new_id(self) -> str:
        return uuid.uuid4().hex[:20]

    # --- transactions -----------------------------------------------------

    def run_transaction(self, fn: Callable[[Transaction], T]) -> T:
        for _ in range(self._max_attempts):
            tx = _MemoryTransaction(self)
            result = fn(tx)
            with self._lock:
                if tx.is_stale():
                    continue
                self._commit(tx.writes)
            run_callbacks(tx.callbacks)
            return result
        raise TransactionContentionError("Transaction aborted by concurrent writes")

    def _version(self, collection: str, doc_id: str) -> int:
        entry = self._docs[collection].get(doc_id)
        return entry[0] if entry else 0

    def _commit(self, writes: list[tuple[str, str, str, Doc]]) -> None:
        # None marks a deleted document.
        staged: dict[tuple[str, str], Doc | None] = {}

        def current(key: tuple[str, str]) -> Doc | None:
            if key in staged:
                return staged[key]
            entry = self._docs[key[0]].get(key[1])
            return copy.deepcopy(entry[1]) if entry else None

        # Validate everything before touching state so a failure is atomic.
        for op, collection, doc_id, data in writes:
            key = (collection, doc_id)
            existing = current(key)
            if op == "create":
                if existing is not None:
                    raise DocumentExistsError(f"{collection}/{doc_id} already exists")
                staged[key] = copy.deepcopy(data)
            elif op == "set":
                staged[key] = copy.deepcopy(data)
            elif op == "merge":
                staged[key] = {**(existing or {}), **copy.deepcopy(data)}
            elif op == "update":
                if existing is None:
                    raise DocumentMissingError(f"{collection}/{doc_id} does not exist")
                staged[key] = {**existing, **copy.deepcopy(data)}
            elif op == "delete":
                staged[key] = None

        self._persist(staged)
        for (collection, doc_id), data in staged.items():
            if data is None:
                self._docs[collection].pop(doc_id, None)
            else:
                self._docs[collection][doc_id] = (self._next_version, data)
            self._collection_versions[collection] += 1
            self._next_version += 1
        self.commit_count += 1

    def _persist(self, staged: dict[tuple[str, str], Doc | None]) -> None:
        """Hook for durable subclasses: write `staged` (None = delete) or raise;
        nothing is applied then."""

    # Test helper: write documents directly, bypassing transactions.
    def seed(self, collection: str, doc_id: str, data: Doc) -> None:
        _check_storable(data)
        with self._lock:
            self._commit([("set", collection, doc_id, data)])


class _MemoryTransaction:
    def __init__(self, db: InMemoryDatabase):
        self._db = db
        self._read_versions: dict[tuple[str, str], int] = {}
        self._queried: dict[str, int] = {}
        self.writes: list[tuple[str, str, str, Doc]] = []
        self.callbacks: list[Callable[[], None]] = []

    def after_commit(self, callback: Callable[[], None]) -> None:
        self.callbacks.append(callback)

    def _before_read(self) -> None:
        if self.writes:
            raise ReadAfterWriteError("All reads must happen before writes in a transaction")

    def get(self, collection: str, doc_id: str) -> Doc | None:
        self._before_read()
        with self._db._lock:
            self._read_versions.setdefault(
                (collection, doc_id), self._db._version(collection, doc_id)
            )
            return self._db.get(collection, doc_id)

    def get_many(self, collection: str, doc_ids: Sequence[str]) -> dict[str, Doc | None]:
        return {doc_id: self.get(collection, doc_id) for doc_id in doc_ids}

    def query(
        self,
        collection: str,
        filters: Sequence[Filter] = (),
        order_by: OrderBy | None = None,
        limit: int | None = None,
    ) -> list[tuple[str, Doc]]:
        self._before_read()
        with self._db._lock:
            self._queried.setdefault(collection, self._db._collection_versions[collection])
            return self._db.query(collection, filters, order_by, limit)

    def is_stale(self) -> bool:
        return any(
            self._db._version(collection, doc_id) != version
            for (collection, doc_id), version in self._read_versions.items()
        ) or any(
            self._db._collection_versions[collection] != version
            for collection, version in self._queried.items()
        )

    def _write(self, op: str, collection: str, doc_id: str, data: Doc) -> None:
        _check_storable(data)
        self.writes.append((op, collection, doc_id, copy.deepcopy(data)))

    def create(self, collection: str, doc_id: str, data: Doc) -> None:
        self._write("create", collection, doc_id, data)

    def set(self, collection: str, doc_id: str, data: Doc, merge: bool = False) -> None:
        self._write("merge" if merge else "set", collection, doc_id, data)

    def update(self, collection: str, doc_id: str, data: Doc) -> None:
        self._write("update", collection, doc_id, data)

    def delete(self, collection: str, doc_id: str) -> None:
        self.writes.append(("delete", collection, doc_id, {}))

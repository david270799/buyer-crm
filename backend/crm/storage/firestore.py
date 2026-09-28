"""Database implementation on top of google-cloud-firestore (via firebase-admin)."""

import random
import threading
import time
import uuid
from collections.abc import Callable, Sequence

from google.api_core import exceptions as gexc
from google.cloud.firestore_v1 import Client, Query, transactional
from google.cloud.firestore_v1 import ReadAfterWriteError as FirestoreReadAfterWriteError
from google.cloud.firestore_v1.base_query import FieldFilter

from crm.storage.base import (
    Doc,
    DocumentExistsError,
    DocumentMissingError,
    Filter,
    OrderBy,
    ReadAfterWriteError,
    StorageError,
    T,
    Transaction,
    TransactionContentionError,
    run_callbacks,
)


def _exception_chain(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _translate(exc: BaseException) -> StorageError | None:
    """Map Firestore errors (possibly wrapped by a failed rollback) to ours."""
    for item in _exception_chain(exc):
        if isinstance(item, gexc.AlreadyExists):
            return DocumentExistsError(str(item))
        if isinstance(item, gexc.NotFound):
            return DocumentMissingError(str(item))
        if isinstance(item, FirestoreReadAfterWriteError):
            return ReadAfterWriteError(str(item))
        # ABORTED comes either wrapped in ValueError (commit retries exhausted)
        # or bare, when a read inside the transaction hits a lock timeout.
        if isinstance(item, gexc.Aborted):
            return TransactionContentionError(str(item))
    return None


class _ScanCache:
    """Short-lived copy of whole-collection reads (`scan`).

    Every transaction that writes to the collection bumps the generation, so
    the CRM's own changes are visible immediately; edits made elsewhere (the
    Firebase console) show up once the entry expires. A scan that started
    before a write never stores its (older) result.
    """

    def __init__(self, ttl_seconds: float):
        self.ttl = ttl_seconds
        self.lock = threading.Lock()
        self.generation = 0
        self.rows: list[tuple[str, Doc]] | None = None
        self.loaded_at = 0.0

    def fresh(self) -> list[tuple[str, Doc]] | None:
        with self.lock:
            if self.rows is not None and time.monotonic() - self.loaded_at < self.ttl:
                return list(self.rows)
            return None

    def store(self, generation: int, rows: list[tuple[str, Doc]]) -> None:
        with self.lock:
            if generation == self.generation:
                self.rows, self.loaded_at = rows, time.monotonic()

    def invalidate(self) -> None:
        with self.lock:
            self.generation += 1
            self.rows = None


class FirestoreDatabase:
    def __init__(
        self,
        client: Client,
        max_attempts: int = 5,
        contention_rounds: int = 4,
        backoff_base_seconds: float = 0.2,
        scan_cache_seconds: float = 0,
        cached_collections: Sequence[str] = (),
    ):
        self._client = client
        self._max_attempts = max_attempts
        self._contention_rounds = contention_rounds
        self._backoff_base = backoff_base_seconds
        self._scan_caches = (
            {name: _ScanCache(scan_cache_seconds) for name in cached_collections}
            if scan_cache_seconds > 0
            else {}
        )

    @property
    def client(self) -> Client:
        return self._client

    def _ref(self, collection: str, doc_id: str):
        return self._client.collection(collection).document(doc_id)

    def _build_query(
        self,
        collection: str,
        filters: Sequence[Filter],
        order_by: OrderBy | None,
        limit: int | None,
    ):
        query = self._client.collection(collection)
        for flt in filters:
            query = query.where(filter=FieldFilter(flt.field, flt.op, flt.value))
        if order_by is not None:
            direction = Query.DESCENDING if order_by.descending else Query.ASCENDING
            query = query.order_by(order_by.field, direction=direction)
        if limit is not None:
            query = query.limit(limit)
        return query

    # --- non-transactional reads ------------------------------------------

    def get(self, collection: str, doc_id: str) -> Doc | None:
        snapshot = self._ref(collection, doc_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def get_many(self, collection: str, doc_ids: Sequence[str]) -> dict[str, Doc | None]:
        return _get_many(self._client, [self._ref(collection, i) for i in doc_ids], None)

    def query(
        self,
        collection: str,
        filters: Sequence[Filter] = (),
        order_by: OrderBy | None = None,
        limit: int | None = None,
    ) -> list[tuple[str, Doc]]:
        query = self._build_query(collection, filters, order_by, limit)
        return [(snap.id, snap.to_dict()) for snap in query.stream()]

    def scan(self, collection: str) -> list[tuple[str, Doc]]:
        cache = self._scan_caches.get(collection)
        if cache is None:
            return self.query(collection)
        rows = cache.fresh()
        if rows is not None:
            return rows
        with cache.lock:
            generation = cache.generation
        rows = self.query(collection)
        cache.store(generation, rows)
        return list(rows)

    def list_ids(self, collection: str) -> list[str]:
        return [ref.id for ref in self._client.collection(collection).list_documents()]

    def new_id(self) -> str:
        return uuid.uuid4().hex[:20]

    # --- transactions -----------------------------------------------------

    def run_transaction(self, fn: Callable[[Transaction], T]) -> T:
        # The Python client retries aborted transactions immediately, without
        # backoff, so a few truly simultaneous writers to one document (the
        # client balance) can exhaust its attempts. Re-running the whole
        # transaction after a jittered pause is safe: every attempt re-reads
        # current state, and the failed attempt was rolled back.
        for round_number in range(self._contention_rounds):
            try:
                return self._run_once(fn)
            except TransactionContentionError:
                if round_number == self._contention_rounds - 1:
                    raise
                time.sleep(random.uniform(0, self._backoff_base * 2**round_number))
        raise AssertionError("unreachable")

    def _run_once(self, fn: Callable[[Transaction], T]) -> T:
        transaction = self._client.transaction(max_attempts=self._max_attempts)
        touched: set[str] = set()
        callbacks: list[Callable[[], None]] = []

        @transactional
        def _run(txn):
            callbacks.clear()  # only the attempt that commits counts
            return fn(_FirestoreTransaction(self, txn, touched, callbacks))

        try:
            result = _run(transaction)
        except (gexc.GoogleAPIError, ValueError, FirestoreReadAfterWriteError) as exc:
            # Only Firestore-originated errors are translated; application
            # errors raised by `fn` propagate unchanged.
            translated = _translate(exc)
            if translated is None:
                raise
            raise translated from exc
        finally:
            # Conservative: any attempted write drops the cached scan.
            for name in touched:
                if name in self._scan_caches:
                    self._scan_caches[name].invalidate()
        run_callbacks(callbacks)
        return result


def _get_many(client: Client, refs: list, transaction) -> dict[str, Doc | None]:
    result: dict[str, Doc | None] = {ref.id: None for ref in refs}
    if not refs:
        return result
    for snapshot in client.get_all(refs, transaction=transaction):
        result[snapshot.id] = snapshot.to_dict() if snapshot.exists else None
    return result


class _FirestoreTransaction:
    def __init__(
        self, db: FirestoreDatabase, txn, touched: set[str], callbacks: list[Callable[[], None]]
    ):
        self._db = db
        self._txn = txn
        self._touched = touched
        self._callbacks = callbacks

    def after_commit(self, callback: Callable[[], None]) -> None:
        self._callbacks.append(callback)

    def get(self, collection: str, doc_id: str) -> Doc | None:
        snapshot = self._db._ref(collection, doc_id).get(transaction=self._txn)
        return snapshot.to_dict() if snapshot.exists else None

    def get_many(self, collection: str, doc_ids: Sequence[str]) -> dict[str, Doc | None]:
        refs = [self._db._ref(collection, doc_id) for doc_id in doc_ids]
        return _get_many(self._db.client, refs, self._txn)

    def query(
        self,
        collection: str,
        filters: Sequence[Filter] = (),
        order_by: OrderBy | None = None,
        limit: int | None = None,
    ) -> list[tuple[str, Doc]]:
        query = self._db._build_query(collection, filters, order_by, limit)
        return [(snap.id, snap.to_dict()) for snap in query.stream(transaction=self._txn)]

    def create(self, collection: str, doc_id: str, data: Doc) -> None:
        self._touched.add(collection)
        self._txn.create(self._db._ref(collection, doc_id), data)

    def set(self, collection: str, doc_id: str, data: Doc, merge: bool = False) -> None:
        self._touched.add(collection)
        self._txn.set(self._db._ref(collection, doc_id), data, merge=merge)

    def update(self, collection: str, doc_id: str, data: Doc) -> None:
        self._touched.add(collection)
        self._txn.update(self._db._ref(collection, doc_id), data)

    def delete(self, collection: str, doc_id: str) -> None:
        self._touched.add(collection)
        self._txn.delete(self._db._ref(collection, doc_id))

"""Storage port used by repositories and services.

Services never import Firestore directly. They receive a `Database` and run
multi-document logic inside `run_transaction`, which gives Firestore's
guarantees: all reads first, then writes; the whole function is re-run on
contention; commit is all-or-nothing.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

Doc = dict[str, Any]
T = TypeVar("T")

logger = logging.getLogger(__name__)


class StorageError(Exception):
    pass


class DocumentExistsError(StorageError):
    """`create` hit an existing document."""


class DocumentMissingError(StorageError):
    """`update` hit a missing document."""


class TransactionContentionError(StorageError):
    """The transaction kept conflicting with concurrent writes."""


class ReadAfterWriteError(StorageError):
    """A transaction tried to read after it had already written."""


@dataclass(frozen=True)
class Filter:
    field: str
    op: str  # "==", "!=", "<", "<=", ">", ">=", "in", "array_contains"
    value: Any


@dataclass(frozen=True)
class OrderBy:
    field: str
    descending: bool = False


class Reader(Protocol):
    def get(self, collection: str, doc_id: str) -> Doc | None: ...

    def get_many(self, collection: str, doc_ids: Sequence[str]) -> dict[str, Doc | None]: ...

    def query(
        self,
        collection: str,
        filters: Sequence[Filter] = (),
        order_by: OrderBy | None = None,
        limit: int | None = None,
    ) -> list[tuple[str, Doc]]: ...


class Transaction(Reader, Protocol):
    def create(self, collection: str, doc_id: str, data: Doc) -> None: ...

    def set(self, collection: str, doc_id: str, data: Doc, merge: bool = False) -> None: ...

    def update(self, collection: str, doc_id: str, data: Doc) -> None: ...

    def after_commit(self, callback: Callable[[], None]) -> None:
        """Run `callback` once this transaction has committed (never if it
        fails). Callbacks must be instant; their errors are logged, not raised."""
        ...


class Database(Reader, Protocol):
    def run_transaction(self, fn: Callable[[Transaction], T]) -> T: ...

    def scan(self, collection: str) -> list[tuple[str, Doc]]:
        """Every document of a collection; may be served from a short-lived cache."""
        ...

    def list_ids(self, collection: str) -> list[str]: ...

    def new_id(self) -> str: ...


def run_callbacks(callbacks: Sequence[Callable[[], None]]) -> None:
    """After-commit callbacks: the commit already happened, so they must not raise."""
    for callback in callbacks:
        try:
            callback()
        except Exception:  # noqa: BLE001
            logger.warning("After-commit callback failed", exc_info=True)

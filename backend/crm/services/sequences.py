"""Transactional sequence numbers (`counters/orders`, `counters/shipments`).

"Read the last ID and add one" outside a transaction can hand the same ID to
two concurrent callers. Here the counter is read and advanced inside the
same transaction that creates the document, and the document itself is
written with `create`, so a duplicate ID is impossible even if the counter
is ever behind.
"""

from collections.abc import Callable
from datetime import datetime

from crm.domain.errors import ConflictError
from crm.repositories import CounterRepository
from crm.storage import Database, Transaction, TransactionContentionError
from crm.storage.base import T

# How many occupied IDs to skip when the counter is behind the data.
_MAX_SKIP = 50


class CounterNotInitialized(Exception):
    def __init__(self, name: str):
        super().__init__(name)
        self.name = name


class SequenceAllocator:
    def __init__(self, db: Database, counters: CounterRepository):
        self._db = db
        self._counters = counters

    def reserve(
        self,
        tx: Transaction,
        name: str,
        is_taken: Callable[[int], bool],
    ) -> int:
        """Read phase: return the next free number. Call `commit` to advance."""
        number = self._counters.get_next(tx, name)
        if number is None:
            raise CounterNotInitialized(name)
        for _ in range(_MAX_SKIP):
            if not is_taken(number):
                return number
            number += 1
        raise ConflictError(
            f"Счётчик counters/{name} сильно отстаёт от данных. Проверьте его вручную."
        )

    def commit(self, tx: Transaction, name: str, used_number: int, now: datetime) -> None:
        self._counters.set_next(tx, name, used_number + 1, now)

    def run(
        self,
        name: str,
        current_max: Callable[[], int],
        now: Callable[[], datetime],
        fn: Callable[[Transaction], T],
    ) -> T:
        """Run `fn` in a transaction, initialising the counter on first use."""
        try:
            return self._db.run_transaction(fn)
        except CounterNotInitialized:
            self._initialise(name, current_max(), now())
            return self._db.run_transaction(fn)

    def _initialise(self, name: str, max_existing: int, now: datetime) -> None:
        def init(tx: Transaction) -> None:
            if self._counters.get_next(tx, name) is None:
                self._counters.set_next(tx, name, max_existing + 1, now)

        try:
            self._db.run_transaction(init)
        except TransactionContentionError:
            # Someone else initialised it concurrently; that is fine.
            pass

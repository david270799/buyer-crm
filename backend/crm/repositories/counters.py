from datetime import datetime

from crm.storage import Reader, Transaction


class CounterRepository:
    """`counters/{name}.next_id`: the next number to hand out."""

    collection = "counters"

    def get_next(self, reader: Reader, name: str) -> int | None:
        data = reader.get(self.collection, name)
        if data is None:
            return None
        value = data.get("next_id")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def set_next(self, tx: Transaction, name: str, next_id: int, now: datetime) -> None:
        tx.set(self.collection, name, {"next_id": next_id, "updated_at": now}, merge=True)

    def get_floor(self, reader: Reader, name: str) -> int:
        """Highest number that must never be handed out again (0 if none).

        Set when a deleted order had money history: its ledger entries keep
        their deterministic IDs (`order_charge_N5`), so a new order with the
        same number would look already charged.
        """
        data = reader.get(self.collection, name) or {}
        value = data.get("floor")
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    def set_after_delete(
        self, tx: Transaction, name: str, next_id: int, floor: int, now: datetime
    ) -> None:
        tx.set(
            self.collection,
            name,
            {"next_id": next_id, "floor": floor, "updated_at": now},
            merge=True,
        )

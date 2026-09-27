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

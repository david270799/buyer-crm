from datetime import UTC, datetime
from typing import Any

from crm.domain.events import Event
from crm.storage import Filter, OrderBy, Reader, Transaction

_EPOCH = datetime.min.replace(tzinfo=UTC)  # comparable with the stored (aware) times


class EventRepository:
    """`events`: append-only feed for order history and notifications.

    Queries use only single-field indexes (created_at, order_ids), so no
    composite index has to be deployed to Firestore.
    """

    collection = "events"

    def create(self, tx: Transaction, event_id: str, data: dict[str, Any]) -> None:
        tx.create(self.collection, event_id, data)

    def page(
        self,
        reader: Reader,
        *,
        before: datetime | None = None,
        after: datetime | None = None,
        limit: int = 100,
    ) -> list[Event]:
        filters = []
        if before is not None:
            filters.append(Filter("created_at", "<", before))
        if after is not None:
            filters.append(Filter("created_at", ">", after))
        rows = reader.query(
            self.collection, filters, order_by=OrderBy("created_at", descending=True), limit=limit
        )
        return [Event.from_doc(doc_id, data) for doc_id, data in rows]

    def pending_delivery(self, reader: Reader, limit: int = 50) -> list[Event]:
        """Events waiting for a Telegram notification, oldest first.

        Sorted here: an equality filter plus ordering on another field would
        need a composite index.
        """
        rows = reader.query(self.collection, [Filter("delivery", "==", "pending")], limit=limit)
        events = [Event.from_doc(doc_id, data) for doc_id, data in rows]
        return sorted(events, key=lambda e: e.created_at or _EPOCH)

    def set_delivery(self, tx: Transaction, event_id: str, data: dict[str, Any]) -> None:
        tx.update(self.collection, event_id, data)

    def delete(self, tx: Transaction, event_id: str) -> None:
        tx.delete(self.collection, event_id)

    def set_order_ids(self, tx: Transaction, event_id: str, order_ids: list[str]) -> None:
        tx.update(self.collection, event_id, {"order_ids": order_ids})

    def for_order(self, reader: Reader, order_id: str, limit: int = 200) -> list[Event]:
        rows = reader.query(
            self.collection, [Filter("order_ids", "array_contains", order_id)], limit=limit
        )
        events = [Event.from_doc(doc_id, data) for doc_id, data in rows]
        return sorted(events, key=lambda e: e.created_at or _EPOCH, reverse=True)


class EventReadsRepository:
    """`event_reads/{user}`: when a user last opened the notifications."""

    collection = "event_reads"

    def seen_at(self, reader: Reader, user_key: str) -> datetime | None:
        data = reader.get(self.collection, user_key)
        value = data.get("seen_at") if data else None
        return value if isinstance(value, datetime) else None

    def mark(self, tx: Transaction, user_key: str, now: datetime) -> None:
        tx.set(self.collection, user_key, {"seen_at": now}, merge=True)

"""Client-facing events: the order history and the notifications bell.

Every event is written by the backend in the same transaction as the change
it describes, so the feed can never disagree with the data. Texts are meant
for the client: they never contain purchase prices, profit or internal
comments.

Notification policy (IMPORTANT_EVENTS below) follows the owner's rule: a
cancelled or re-bought order, a sent shipment and similar money-relevant
news are "important"; everything else, including a normal buy-out, is shown
only under "Все". Purely technical edits (brand, size, photo) create no event.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    ORDER_CREATED = "order_created"
    ORDER_BOUGHT = "order_bought"
    ORDER_REBOUGHT = "order_rebought"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_WAREHOUSE = "order_warehouse"
    ORDER_DELIVERED = "order_delivered"
    ORDER_STATUS = "order_status"
    COMMENT = "comment"
    ATTENTION = "attention"
    SHIPMENT_SENT = "shipment_sent"
    SHIPMENT_UPDATED = "shipment_updated"
    SHIPPING_COST = "shipping_cost"
    DEPOSIT = "deposit"
    ADJUSTMENT = "adjustment"
    RATE = "rate"


IMPORTANT_EVENTS = frozenset(
    {
        EventType.ORDER_REBOUGHT,
        EventType.ORDER_CANCELLED,
        EventType.SHIPMENT_SENT,
        EventType.ATTENTION,
        EventType.SHIPPING_COST,
        EventType.ADJUSTMENT,
    }
)


def is_important(event_type: EventType) -> bool:
    return event_type in IMPORTANT_EVENTS


@dataclass
class Event:
    id: str
    type: EventType | None
    important: bool
    title: str
    body: str | None
    order_ids: list[str] = field(default_factory=list)
    shipment_id: str | None = None
    amount_krw: int | None = None
    created_at: datetime | None = None

    @classmethod
    def from_doc(cls, doc_id: str, data: dict[str, Any]) -> "Event":
        try:
            event_type: EventType | None = EventType(data.get("type"))
        except ValueError:
            event_type = None
        order_ids = data.get("order_ids")
        amount = data.get("amount_krw")
        created = data.get("created_at")
        return cls(
            id=doc_id,
            type=event_type,
            important=bool(data.get("important", False)),
            title=str(data.get("title") or ""),
            body=data.get("body") or None,
            order_ids=[str(i) for i in order_ids] if isinstance(order_ids, list) else [],
            shipment_id=data.get("shipment_id") or None,
            amount_krw=amount if isinstance(amount, int) and not isinstance(amount, bool) else None,
            created_at=created if isinstance(created, datetime) else None,
        )

"""Role-aware projections of domain objects.

This is the single place that decides which order fields a CLIENT may see.
The bot and the future Mini App / dashboard API must render from these views,
never from raw documents, so that purchase_price, profit and internal_comment
cannot leak to the client.
"""

from typing import Any

from crm.domain.enums import STATUS_FLOW, OrderStatus, Role
from crm.domain.models import Order, status_timestamp_field

CLIENT_ORDER_FIELDS = (
    "id",
    "status",
    "brand",
    "model",
    "size",
    "client_price",
    "cargo_code",
    "shipment_id",
    "photo_url",
    "thumbnail_url",
    "source_url",
    "client_comment",
    "attention_required",
)

ADMIN_ONLY_ORDER_FIELDS = (
    "purchase_price",
    "profit",
    "charged_amount_krw",
    "internal_comment",
    "source_chat_id",
    "source_message_id",
    "created_by",
    "updated_by",
)

_CLIENT_TIMESTAMPS = ("created_at",) + tuple(
    status_timestamp_field(status) for status in (*STATUS_FLOW[1:], OrderStatus.CANCELLED)
)


def order_view(order: Order, role: Role) -> dict[str, Any]:
    fields = CLIENT_ORDER_FIELDS + (ADMIN_ONLY_ORDER_FIELDS if role is Role.ADMIN else ())
    view: dict[str, Any] = {name: getattr(order, name) for name in fields}
    view["status"] = order.status.value if order.status else None
    timestamp_names = _CLIENT_TIMESTAMPS + (("updated_at",) if role is Role.ADMIN else ())
    view["timestamps"] = {
        name: order.timestamps[name] for name in timestamp_names if name in order.timestamps
    }
    return view

"""Role-aware projections of domain objects.

This is the single place that decides which order fields a CLIENT may see.
The bot and the future Mini App / dashboard API must render from these views,
never from raw documents, so that purchase_price, profit and internal_comment
cannot leak to the client.
"""

from typing import Any

from crm.domain.enums import STATUS_FLOW, OrderStatus, Role
from crm.domain.models import LedgerEntry, Order, Shipment, status_timestamp_field

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
    "client_comment",
    "attention_required",
)

ADMIN_ONLY_ORDER_FIELDS = (
    "source_url",  # where the item was bought: the buyer's own reference
    "purchase_price",
    "profit",
    "charged_amount_krw",
    "internal_comment",
    "purchases",
    "rebuy_count",
    "recognition",
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


def shipment_view(shipment: Shipment, role: Role) -> dict[str, Any]:
    view: dict[str, Any] = {
        "id": shipment.id,
        "shipment_number": shipment.shipment_number,
        "tracking_code": shipment.tracking_code,
        "box_number": shipment.box_number,
        "weight_kg": shipment.weight_kg,
        "shipping_cost_krw": shipment.shipping_cost_krw,
        "shipment_date": shipment.shipment_date,
        "photo_url": shipment.photo_url,
        "thumbnail_url": shipment.thumbnail_url,
        "order_ids": list(shipment.order_ids),
        "order_count": len(shipment.order_ids),
        "comment": shipment.comment,
        "created_at": shipment.created_at,
    }
    if role is Role.ADMIN:
        view["shipping_charged_krw"] = shipment.shipping_charged_krw
        view["created_by"] = shipment.created_by
        view["updated_at"] = shipment.updated_at
    return view


def ledger_view(entry: LedgerEntry, role: Role) -> dict[str, Any]:
    view: dict[str, Any] = {
        "id": entry.id,
        "type": entry.type.value if entry.type else None,
        "amount_krw": entry.amount_krw,
        "balance_before": entry.balance_before,
        "balance_after": entry.balance_after,
        "order_id": entry.order_id,
        "shipment_id": entry.shipment_id,
        "comment": entry.comment,
        "created_at": entry.created_at,
    }
    if role is Role.ADMIN:
        view["created_by"] = entry.created_by
        view["source"] = entry.source
    return view

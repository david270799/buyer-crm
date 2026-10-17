"""Role-aware projections of domain objects.

This is the single place that decides which order fields a CLIENT may see.
The bot and the future Mini App / dashboard API must render from these views,
never from raw documents, so that purchase_price, profit and internal_comment
cannot leak to the client.
"""

from typing import Any

from crm.domain.enums import STATUS_FLOW, LedgerType, OrderStatus, Role
from crm.domain.models import LedgerEntry, Order, Shipment, status_timestamp_field

CLIENT_ORDER_FIELDS = (
    "id",
    "status",
    "brand",
    "model",
    "size",
    "size_kr",
    "category",
    "client_price",
    "cargo_code",
    "shipment_id",
    "photo_url",
    "thumbnail_url",
    "client_comment",
    "attention_required",
    # The warehouse photo (16.10.2026: the client sees it too, swiped after the main photo).
    "arrival_photo_url",
    "arrival_thumbnail_url",
)

ADMIN_ONLY_ORDER_FIELDS = (
    "source_url",  # where the item was bought: the buyer's own reference
    "shop",
    "arrival_check",
    "review_ko",
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
        "photos": [dict(p) for p in shipment.photos],
        "order_ids": list(shipment.order_ids),
        "order_count": len(shipment.order_ids),
        "comment": shipment.comment,
        "created_at": shipment.created_at,
        "watch_count": shipment.watch_count,
    }
    if role is Role.ADMIN:
        view["shipping_charged_krw"] = shipment.shipping_charged_krw
        view["watch_charged_krw"] = shipment.watch_charged_krw
        view["watch_price_usd"] = shipment.watch_price_usd
        view["watch_krw_per_usd"] = (
            float(shipment.watch_krw_per_usd) if shipment.watch_krw_per_usd else None
        )
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


def ledger_rows(entries: list[LedgerEntry], role: Role) -> list[dict[str, Any]]:
    """Balance history rows (newest first). A re-purchase is shown on its order's
    charge line instead of a separate «+₩ 30,000» (the owner, 17.10.2026): one row
    with the final amount, the first price crossed out. It stands where the last
    re-purchase stands, so its «после» is that entry's balance. The ledger itself
    is untouched — append-only, every entry kept."""
    by_order: dict[str, list[LedgerEntry]] = {}
    for entry in entries:
        if entry.order_id and entry.type in (LedgerType.ORDER_CHARGE, LedgerType.ORDER_REBUY):
            by_order.setdefault(entry.order_id, []).append(entry)
    merged: dict[str, dict[str, Any]] = {}  # id of the newest re-purchase → merged row
    hidden: set[str] = set()
    for group in by_order.values():
        charges = [e for e in group if e.type is LedgerType.ORDER_CHARGE]
        rebuys = [e for e in group if e.type is LedgerType.ORDER_REBUY]
        if len(charges) != 1 or not rebuys:
            continue  # the charge is older than this page: rows stay as they are
        charge, newest = charges[0], rebuys[0]  # entries come newest first
        row = ledger_view(charge, role)
        row.update(
            amount_krw=charge.amount_krw + sum(e.amount_krw for e in rebuys),
            original_amount_krw=charge.amount_krw,
            rebuy_count=len(rebuys),
            balance_after=newest.balance_after,
            created_at=newest.created_at,
            bought_at=charge.created_at,
        )
        merged[newest.id] = row
        hidden.update(e.id for e in group)
    rows = []
    for entry in entries:
        if entry.id in merged:
            rows.append(merged[entry.id])
        elif entry.id not in hidden:
            rows.append(ledger_view(entry, role))
    return rows

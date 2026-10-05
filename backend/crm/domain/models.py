"""Typed views over Firestore documents.

Parsing is lenient: documents may also be created or edited by hand in the
Firebase console. Unknown fields are ignored here and are never deleted —
services only ever update the fields they own.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from crm.domain.enums import LedgerType, OrderStatus, parse_status
from crm.domain.money import to_int_amount

Doc = dict[str, Any]


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dt(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None


def status_timestamp_field(status: OrderStatus) -> str:
    return f"{status.value}_at"


@dataclass
class Order:
    id: str
    status: OrderStatus | None
    status_raw: Any = None
    brand: str | None = None
    model: str | None = None
    size: str | None = None
    purchase_price: int | None = None
    client_price: int | None = None
    profit: int | None = None
    # Amount of this order currently charged to the client balance.
    charged_amount_krw: int = 0
    cargo_code: str | None = None
    shipment_id: str | None = None
    photo_url: str | None = None
    thumbnail_url: str | None = None
    source_url: str | None = None
    source_chat_id: int | None = None
    source_message_id: int | None = None
    client_comment: str | None = None
    internal_comment: str | None = None
    attention_required: bool = False
    # Admin only: every purchase attempt (first buy and each re-purchase).
    purchases: list[Doc] = field(default_factory=list)
    rebuy_count: int = 0
    # Admin only: what Gemini read from the client's photo (see services/recognition).
    recognition: Doc | None = None
    timestamps: dict[str, datetime] = field(default_factory=dict)
    created_by: str | None = None
    updated_by: str | None = None

    @classmethod
    def from_doc(cls, doc_id: str, data: Doc) -> "Order":
        status = parse_status(data.get("status"))
        client_price = to_int_amount(data.get("client_price"))
        purchase_price = to_int_amount(data.get("purchase_price"))

        # Only this CRM charges orders, and it always records what it charged.
        # A missing value (e.g. a document typed in the Firebase console) means
        # nothing was charged: money never moves on a guess.
        charged = to_int_amount(data.get("charged_amount_krw")) or 0

        profit = to_int_amount(data.get("profit"))
        if profit is None and client_price is not None and purchase_price is not None:
            profit = client_price - purchase_price

        timestamps = {
            key: value
            for key, value in data.items()
            if key.endswith("_at") and isinstance(value, datetime)
        }
        return cls(
            id=doc_id,
            status=status,
            status_raw=data.get("status"),
            brand=_str_or_none(data.get("brand")),
            model=_str_or_none(data.get("model")),
            size=_str_or_none(data.get("size")),
            purchase_price=purchase_price,
            client_price=client_price,
            profit=profit,
            charged_amount_krw=charged,
            cargo_code=_str_or_none(data.get("cargo_code")),
            shipment_id=_str_or_none(data.get("shipment_id")),
            photo_url=_str_or_none(data.get("photo_url")),
            thumbnail_url=_str_or_none(data.get("thumbnail_url")),
            source_url=_str_or_none(data.get("source_url")),
            source_chat_id=_int_or_none(data.get("source_chat_id")),
            source_message_id=_int_or_none(data.get("source_message_id")),
            client_comment=_str_or_none(data.get("client_comment")),
            internal_comment=_str_or_none(data.get("internal_comment")),
            attention_required=bool(data.get("attention_required", False)),
            purchases=[dict(p) for p in data.get("purchases") or [] if isinstance(p, dict)],
            rebuy_count=_int_or_none(data.get("rebuy_count")) or 0,
            recognition=dict(data["recognition"])
            if isinstance(data.get("recognition"), dict)
            else None,
            timestamps=timestamps,
            created_by=_str_or_none(data.get("created_by")),
            updated_by=_str_or_none(data.get("updated_by")),
        )

    @property
    def title(self) -> str | None:
        parts = [part for part in (self.brand, self.model) if part]
        return " ".join(parts) or None

    @property
    def is_charged(self) -> bool:
        return self.charged_amount_krw > 0

    def timestamp(self, name: str) -> datetime | None:
        return self.timestamps.get(name)


@dataclass
class ClientInfo:
    id: str
    telegram_id: int | None
    name: str | None
    # None means the stored value is missing or unreadable: financial
    # operations must refuse instead of assuming zero.
    balance: int | None

    @classmethod
    def from_doc(cls, doc_id: str, data: Doc) -> "ClientInfo":
        return cls(
            id=doc_id,
            telegram_id=_int_or_none(data.get("telegram_id")),
            name=_str_or_none(data.get("name")),
            balance=to_int_amount(data.get("balance")),
        )


@dataclass
class Shipment:
    id: str
    shipment_number: int | None
    tracking_code: str | None
    box_number: str | None
    weight_kg: float | None
    shipping_cost_krw: int | None
    shipment_date: datetime | None
    photo_url: str | None
    order_ids: list[str]
    comment: str | None
    created_at: datetime | None
    created_by: str | None
    # What is currently charged to the client balance for shipping, and how
    # many shipping ledger entries exist (for deterministic entry IDs).
    shipping_charged_krw: int = 0
    shipping_charge_seq: int = 0
    thumbnail_url: str | None = None
    updated_at: datetime | None = None
    # All photos (the first one is also photo_url / thumbnail_url).
    photos: list[dict[str, str | None]] = field(default_factory=list)

    @classmethod
    def from_doc(cls, doc_id: str, data: Doc) -> "Shipment":
        order_ids = data.get("order_ids")
        photos = [
            {"photo_url": p["photo_url"], "thumbnail_url": _str_or_none(p.get("thumbnail_url"))}
            for p in data.get("photos") or []
            if isinstance(p, dict) and isinstance(p.get("photo_url"), str)
        ]
        if not photos and _str_or_none(data.get("photo_url")):
            # Shipments saved before several photos existed.
            photos = [
                {
                    "photo_url": data["photo_url"],
                    "thumbnail_url": _str_or_none(data.get("thumbnail_url")),
                }
            ]
        return cls(
            id=doc_id,
            shipment_number=_int_or_none(data.get("shipment_number")),
            tracking_code=_str_or_none(data.get("tracking_code")),
            box_number=_str_or_none(data.get("box_number")),
            weight_kg=_float_or_none(data.get("weight_kg")),
            shipping_cost_krw=to_int_amount(data.get("shipping_cost_krw")),
            shipment_date=_dt(data.get("shipment_date")),
            photo_url=_str_or_none(data.get("photo_url")),
            order_ids=[str(i) for i in order_ids] if isinstance(order_ids, list) else [],
            comment=_str_or_none(data.get("comment")),
            created_at=_dt(data.get("created_at")),
            created_by=_str_or_none(data.get("created_by")),
            shipping_charged_krw=to_int_amount(data.get("shipping_charged_krw")) or 0,
            shipping_charge_seq=_int_or_none(data.get("shipping_charge_seq")) or 0,
            thumbnail_url=_str_or_none(data.get("thumbnail_url")),
            updated_at=_dt(data.get("updated_at")),
            photos=photos,
        )


@dataclass
class ProfitEntry:
    """Admin-only extra profit (cashback, rate gains...). Never touches the
    client's balance and is never shown to the client."""

    id: str
    amount_krw: int
    comment: str | None
    created_at: datetime | None
    created_by: str | None

    @classmethod
    def from_doc(cls, doc_id: str, data: Doc) -> "ProfitEntry":
        return cls(
            id=doc_id,
            amount_krw=to_int_amount(data.get("amount_krw")) or 0,
            comment=_str_or_none(data.get("comment")),
            created_at=_dt(data.get("created_at")),
            created_by=_str_or_none(data.get("created_by")),
        )


@dataclass
class LedgerEntry:
    id: str
    type: LedgerType | None
    amount_krw: int
    balance_before: int
    balance_after: int
    order_id: str | None
    shipment_id: str | None
    comment: str | None
    created_at: datetime | None
    created_by: str | None
    source: str | None

    @classmethod
    def from_doc(cls, doc_id: str, data: Doc) -> "LedgerEntry":
        try:
            entry_type: LedgerType | None = LedgerType(data.get("type"))
        except ValueError:
            entry_type = None
        return cls(
            id=doc_id,
            type=entry_type,
            amount_krw=to_int_amount(data.get("amount_krw")) or 0,
            balance_before=to_int_amount(data.get("balance_before")) or 0,
            balance_after=to_int_amount(data.get("balance_after")) or 0,
            order_id=_str_or_none(data.get("order_id")),
            shipment_id=_str_or_none(data.get("shipment_id")),
            comment=_str_or_none(data.get("comment")),
            created_at=_dt(data.get("created_at")),
            created_by=_str_or_none(data.get("created_by")),
            source=_str_or_none(data.get("source")),
        )


@dataclass
class GeneralSettings:
    krw_per_usd: Decimal | None
    updated_at: datetime | None = None
    updated_by: str | None = None

    @classmethod
    def from_doc(cls, data: Doc | None) -> "GeneralSettings":
        if not data:
            return cls(krw_per_usd=None)
        raw = data.get("krw_per_usd")
        rate: Decimal | None = None
        if isinstance(raw, (int, float, str)) and not isinstance(raw, bool):
            try:
                rate = Decimal(str(raw))
            except ArithmeticError:
                rate = None
            if rate is not None and (not rate.is_finite() or rate <= 0):
                rate = None
        return cls(
            krw_per_usd=rate,
            updated_at=_dt(data.get("updated_at")),
            updated_by=_str_or_none(data.get("updated_by")),
        )

from enum import StrEnum


class OrderStatus(StrEnum):
    NEW = "new"
    BOUGHT = "bought"
    WAREHOUSE = "warehouse"
    CARGO = "cargo"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


# Happy path shown in the UI stepper. CANCELLED is outside of it.
STATUS_FLOW: tuple[OrderStatus, ...] = (
    OrderStatus.NEW,
    OrderStatus.BOUGHT,
    OrderStatus.WAREHOUSE,
    OrderStatus.CARGO,
    OrderStatus.DELIVERED,
)

# Statuses after a successful /buy; their profit counts toward totals.
CHARGED_STATUSES = frozenset(
    {OrderStatus.BOUGHT, OrderStatus.WAREHOUSE, OrderStatus.CARGO, OrderStatus.DELIVERED}
)

STATUS_LABELS_RU: dict[OrderStatus, str] = {
    OrderStatus.NEW: "Новый заказ",
    OrderStatus.BOUGHT: "Выкуплен",
    OrderStatus.WAREHOUSE: "На складе",
    OrderStatus.CARGO: "Отправлен",
    OrderStatus.DELIVERED: "Доставлен",
    OrderStatus.CANCELLED: "Отменён",
}

STATUS_ICONS: dict[OrderStatus, str] = {
    OrderStatus.NEW: "🆕",
    OrderStatus.BOUGHT: "🛍",
    OrderStatus.WAREHOUSE: "🏬",
    OrderStatus.CARGO: "📦",
    OrderStatus.DELIVERED: "✅",
    OrderStatus.CANCELLED: "✖️",
}

_STATUS_ALIASES: dict[str, OrderStatus] = {
    **{status.value: status for status in OrderStatus},
    "canceled": OrderStatus.CANCELLED,
    "новый": OrderStatus.NEW,
    "выкуплен": OrderStatus.BOUGHT,
    "куплен": OrderStatus.BOUGHT,
    "склад": OrderStatus.WAREHOUSE,
    "карго": OrderStatus.CARGO,
    "отправлен": OrderStatus.CARGO,
    "доставлен": OrderStatus.DELIVERED,
    "отменен": OrderStatus.CANCELLED,
    "отменён": OrderStatus.CANCELLED,
}


def parse_status(raw: object) -> OrderStatus | None:
    """Parse a status from user input or a stored document; None if unknown."""
    if not isinstance(raw, str):
        return None
    return _STATUS_ALIASES.get(raw.strip().lower())


class Role(StrEnum):
    ADMIN = "admin"
    CLIENT = "client"


class Source(StrEnum):
    TELEGRAM_BOT = "telegram_bot"
    MINI_APP = "mini_app"
    WEB_DASHBOARD = "web_dashboard"
    AI_ASSISTANT = "ai_assistant"
    SYSTEM = "system"


class LedgerType(StrEnum):
    ORDER_CHARGE = "order_charge"
    ORDER_REFUND = "order_refund"
    ORDER_REBUY = "order_rebuy"
    DEPOSIT = "deposit"
    ADJUSTMENT = "adjustment"
    SHIPPING_CHARGE = "shipping_charge"


LEDGER_LABELS_RU: dict[LedgerType, str] = {
    LedgerType.ORDER_CHARGE: "Выкуп заказа",
    LedgerType.ORDER_REFUND: "Возврат за заказ",
    LedgerType.ORDER_REBUY: "Перезаказ",
    LedgerType.DEPOSIT: "Пополнение",
    LedgerType.ADJUSTMENT: "Корректировка",
    LedgerType.SHIPPING_CHARGE: "Доставка",
}

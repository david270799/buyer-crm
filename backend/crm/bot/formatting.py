"""Telegram message texts (HTML parse mode). Every dynamic value goes through `e()`."""

import html
from decimal import Decimal

from crm.domain.enums import (
    LEDGER_LABELS_RU,
    STATUS_FLOW,
    STATUS_ICONS,
    STATUS_LABELS_RU,
    LedgerType,
    OrderStatus,
    Role,
)
from crm.domain.events import Event, EventType
from crm.domain.models import LedgerEntry, Order, Shipment
from crm.domain.money import format_krw, format_usd
from crm.domain.notifications import (
    LEVEL_LABELS,
    RECIPIENT_LABELS,
    NotificationSettings,
    NotifyRecipient,
)
from crm.domain.timeutil import format_date, format_datetime
from crm.domain.views import order_view
from crm.services.finance_service import BalanceView, LedgerResult
from crm.services.ledger import BalanceChange
from crm.services.order_service import BulkResult, BuyResult, CancelResult, RebuyResult
from crm.services.shipment_service import ShipmentUpdateResult, ShipResult


def e(value: object) -> str:
    return html.escape(str(value), quote=False)


def _ids(ids: list[str]) -> str:
    return ", ".join(e(i) for i in ids)


def status_label(status: OrderStatus | None) -> str:
    return STATUS_LABELS_RU[status] if status else "Неизвестный статус"


def stepper(status: OrderStatus | None) -> str:
    """`● ● ● ○ ○` along NEW → BOUGHT → WAREHOUSE → CARGO → DELIVERED."""
    if status is OrderStatus.CANCELLED:
        return "✖️ Отменён"
    if status not in STATUS_FLOW:
        return "○ ○ ○ ○ ○"
    reached = STATUS_FLOW.index(status)
    return " ".join("●" if i <= reached else "○" for i in range(len(STATUS_FLOW)))


def _money(amount: int | None) -> str:
    return format_krw(amount) if amount is not None else "—"


def _order_heading(order: Order) -> str:
    icon = STATUS_ICONS.get(order.status, "•") if order.status else "•"
    return f"{icon} <b>{e(order.id)}</b> · {e(status_label(order.status))}"


def order_details(order: Order, role: Role) -> str:
    """`role` is the audience of the message (see crm.bot.access.audience_for)."""
    view = order_view(order, role)
    lines = [_order_heading(order)]
    title = " ".join(part for part in (view["brand"], view["model"]) if part)
    if title:
        lines.append(e(title))
    if view["size"]:
        lines.append(f"Размер: {e(view['size'])}")
    lines.append(f"Цена: {_money(view['client_price'])}")
    if role is Role.ADMIN:
        lines.append(
            f"Закупка: {_money(view['purchase_price'])} · Прибыль: {_money(view['profit'])}"
        )
        lines.append(f"Списано с баланса: {_money(view['charged_amount_krw'])}")
    lines.append(stepper(order.status))
    if view["cargo_code"]:
        lines.append(f"Трек: <code>{e(view['cargo_code'])}</code>")
    if view["shipment_id"]:
        lines.append(f"Отправка: {e(view['shipment_id'])}")
    if role is Role.ADMIN and view["source_url"]:
        lines.append(f"🔒 Ссылка: {e(view['source_url'])}")
    if view["attention_required"]:
        lines.append("⚠️ <b>Требуется внимание</b>")
    if view["client_comment"]:
        lines.append(f"💬 {e(view['client_comment'])}")
    if role is Role.ADMIN and view.get("internal_comment"):
        lines.append(f"🔒 {e(view['internal_comment'])}")
    stamps = view["timestamps"]
    for name, caption in (
        ("created_at", "Создан"),
        ("bought_at", "Выкуплен"),
        ("warehouse_at", "На складе"),
        ("cargo_at", "Отправлен"),
        ("delivered_at", "Доставлен"),
        ("cancelled_at", "Отменён"),
    ):
        if name in stamps:
            lines.append(f"<i>{caption}: {e(format_datetime(stamps[name]))}</i>")
    return "\n".join(lines)


def _balance_line(before: int, after: int) -> str:
    return f"Баланс: {format_krw(before)} → <b>{format_krw(after)}</b>"


def buy_result(result: BuyResult, audience: Role) -> str:
    """`audience` is CLIENT outside a private admin chat: no purchase price or profit."""
    order = result.order
    if result.already_done:
        return (
            f"ℹ️ Заказ <b>{e(order.id)}</b> уже выкуплен с этими ценами.\n"
            "Повторного списания нет, баланс не изменился."
        )
    lines = [f"✅ Заказ <b>{e(order.id)}</b> выкуплен"]
    if order.title:
        lines.append(e(order.title) + (f" · {e(order.size)}" if order.size else ""))
    if audience is Role.ADMIN:
        lines += [
            f"Закупка: {_money(order.purchase_price)}",
            f"Клиенту: {_money(order.client_price)}",
            f"Прибыль: {_money(order.profit)}",
        ]
        if order.profit is not None and order.profit < 0:
            lines.append("⚠️ Прибыль отрицательная — проверьте цены.")
    else:
        lines.append(f"Цена: {_money(order.client_price)}")
    if result.change:
        lines.append(_balance_line(result.change.balance_before, result.change.balance_after))
    return "\n".join(lines)


def rebuy_result(result: RebuyResult, audience: Role) -> str:
    order = result.order
    if result.already_done:
        return f"ℹ️ Заказ <b>{e(order.id)}</b> уже выкуплен с этими данными — ничего не изменилось."
    lines = [f"🔁 Заказ <b>{e(order.id)}</b> перезаказан"]
    if audience is Role.ADMIN:
        lines.append(
            f"Закупка: {_money(order.purchase_price)} · Клиенту: {_money(order.client_price)} · "
            f"Прибыль: {_money(order.profit)}"
        )
    else:
        lines.append(f"Цена: {_money(order.client_price)}")
    if result.change:
        lines.append(_balance_line(result.change.balance_before, result.change.balance_after))
    else:
        lines.append("Цена для клиента не изменилась — баланс тот же.")
    return "\n".join(lines)


def cancel_result(result: CancelResult) -> str:
    order_id = e(result.order.id)
    if result.already_done:
        return f"ℹ️ Заказ <b>{order_id}</b> уже отменён. Повторного возврата нет."
    lines = [f"✖️ Заказ <b>{order_id}</b> отменён"]
    if result.change:
        lines.append(f"Возврат на баланс: {format_krw(result.refunded_krw, signed=True)}")
        lines.append(_balance_line(result.change.balance_before, result.change.balance_after))
    else:
        lines.append("Списаний по заказу не было — баланс не изменился.")
    return "\n".join(lines)


def _bulk_tail(
    not_found: list[str],
    skipped: list[tuple[str, str]],
    unchanged_label: str,
    unchanged: list[str],
) -> list[str]:
    lines = []
    if unchanged:
        lines.append(f"ℹ️ {unchanged_label}: {_ids(unchanged)}")
    if not_found:
        lines.append(f"⚠️ Не найдено: {_ids(not_found)}")
    if skipped:
        lines.append("⏭ Пропущено:")
        lines += [f" • {e(order_id)} — {e(reason)}" for order_id, reason in skipped]
    return lines


def status_result(status: OrderStatus, result: BulkResult) -> str:
    lines = [f"{STATUS_ICONS[status]} Статус «{e(STATUS_LABELS_RU[status])}»"]
    if result.updated:
        lines.append(f"✅ Обновлено: {_ids(result.updated)}")
    lines += _bulk_tail(result.not_found, result.skipped, "Уже в этом статусе", result.unchanged)
    if len(lines) == 1:
        lines.append("Нечего обновлять.")
    return "\n".join(lines)


def _shipment_title(shipment: Shipment) -> str:
    number = f" #{shipment.shipment_number}" if shipment.shipment_number else ""
    return f"Отправка{number} · {e(shipment.id)}"


def cargo_result(result: ShipResult) -> str:
    lines: list[str] = []
    if result.shipment is not None:
        verb = "📦 Создана" if result.created else "📦"
        lines.append(f"{verb} {_shipment_title(result.shipment)}")
        if result.shipment.tracking_code:
            lines.append(f"Трек: <code>{e(result.shipment.tracking_code)}</code>")
    if result.added:
        lines.append(f"✅ Обновлено: {_ids(result.added)}")
    elif result.shipment is None:
        lines.append("ℹ️ Ни один заказ не отправлен — отправка не создана.")
    lines += _bulk_tail(
        result.not_found, result.skipped, "Уже в этой отправке", result.already_in_shipment
    )
    if result.shipping_change:
        lines.append(_shipping_line(result.shipping_change))
    return "\n".join(lines)


def _shipping_line(change: BalanceChange) -> str:
    return (
        f"🚚 Доставка: {format_krw(change.amount_krw, signed=True)}\n"
        f"{_balance_line(change.balance_before, change.balance_after)}"
    )


def shipment_updated(result: ShipmentUpdateResult) -> str:
    lines = [f"✅ {_shipment_title(result.shipment)} обновлена"]
    if result.shipment.shipping_cost_krw is not None:
        lines.append(f"Стоимость доставки: {format_krw(result.shipment.shipping_cost_krw)}")
    if result.shipping_change:
        lines.append(_shipping_line(result.shipping_change))
    else:
        lines.append("Баланс не изменился.")
    return "\n".join(lines)


def shipment_details(shipment: Shipment, orders: list[Order]) -> str:
    lines = [f"📦 <b>{_shipment_title(shipment)}</b>"]
    date = shipment.shipment_date or shipment.created_at
    lines.append(f"Дата: {e(format_date(date))}")
    if shipment.tracking_code:
        lines.append(f"Трек: <code>{e(shipment.tracking_code)}</code>")
    if shipment.box_number:
        lines.append(f"Коробка: {e(shipment.box_number)}")
    if shipment.weight_kg is not None:
        lines.append(f"Вес: {e(f'{shipment.weight_kg:g}')} кг")
    if shipment.shipping_cost_krw is not None:
        lines.append(f"Доставка: {format_krw(shipment.shipping_cost_krw)}")
    if shipment.comment:
        lines.append(f"💬 {e(shipment.comment)}")
    lines.append(f"Товаров: {len(shipment.order_ids)}")
    by_id = {order.id: order for order in orders}
    for order_id in shipment.order_ids:
        order = by_id.get(order_id)
        title = order.title if order and order.title else ""
        price = f" · {_money(order.client_price)}" if order else ""
        lines.append(f" • {e(order_id)} {e(title)}{price}".rstrip())
    return "\n".join(lines)


def shipments_list(shipments: list[Shipment]) -> str:
    if not shipments:
        return "📦 Отправок пока нет."
    lines = ["📦 <b>Отправки</b>"]
    for shipment in shipments:
        weight = f" · {shipment.weight_kg:g} кг" if shipment.weight_kg is not None else ""
        date = format_date(shipment.shipment_date or shipment.created_at)
        lines.append(
            f"{_shipment_title(shipment)} · {e(date)} · {len(shipment.order_ids)} шт.{e(weight)}"
        )
    return "\n".join(lines)


def balance(view: BalanceView) -> str:
    lines = ["💰 <b>Баланс</b>"]
    krw = format_krw(view.balance_krw)
    lines.append(f"🔴 <b>{krw}</b> (долг)" if view.balance_krw < 0 else f"<b>{krw}</b>")
    if view.balance_usd is not None and view.krw_per_usd is not None:
        lines.append(f"{format_usd(view.balance_usd)}  <i>(курс {_rate(view.krw_per_usd)} ₩/$)</i>")
    else:
        lines.append("<i>Курс USD не задан.</i>")
    return "\n".join(lines)


def _rate(rate: Decimal) -> str:
    return f"{rate.normalize():,f}"


def rate_set(rate: Decimal) -> str:
    return f"✅ Курс обновлён: 1 $ = {_rate(rate)} ₩"


def rate_current(rate: Decimal | None) -> str:
    if rate is None:
        return "Курс USD не задан. Установить: /rate 1350"
    return f"Текущий курс: 1 $ = {_rate(rate)} ₩\nИзменить: /rate 1350"


def ledger_result(result: LedgerResult) -> str:
    entry = result.entry
    label = LEDGER_LABELS_RU.get(entry.type, "Операция") if entry.type else "Операция"
    if result.already_done:
        return f"ℹ️ Эта операция уже была проведена ({e(label)}). Баланс не изменился."
    lines = [f"✅ {e(label)}: {format_krw(entry.amount_krw, signed=True)}"]
    if entry.comment:
        lines.append(f"💬 {e(entry.comment)}")
    lines.append(_balance_line(entry.balance_before, entry.balance_after))
    return "\n".join(lines)


def _ledger_subject(entry: LedgerEntry) -> str:
    label = LEDGER_LABELS_RU.get(entry.type, "Операция") if entry.type else "Операция"
    if entry.type is LedgerType.SHIPPING_CHARGE:
        return entry.comment or f"{label} · {entry.shipment_id}"
    if entry.order_id:
        parts = [entry.order_id, entry.comment]
        if entry.type is LedgerType.ORDER_REFUND:
            parts.insert(0, "Возврат")
        return " · ".join(part for part in parts if part)
    return f"{label} · {entry.comment}" if entry.comment else label


def history(entries: list[LedgerEntry]) -> str:
    if not entries:
        return "🧾 История баланса пуста."
    lines = ["🧾 <b>История баланса</b>"]
    for entry in entries:
        subject = _ledger_subject(entry)
        lines.append(
            f"\n<i>{e(format_date(entry.created_at))}</i> · {e(subject)}\n"
            f"<b>{format_krw(entry.amount_krw, signed=True)}</b>"
        )
    return "\n".join(lines)


EVENT_ICONS = {
    EventType.ORDER_CREATED: "🆕",
    EventType.ORDER_BOUGHT: "🛍",
    EventType.ORDER_REBOUGHT: "🔁",
    EventType.ORDER_CANCELLED: "✖️",
    EventType.ORDER_WAREHOUSE: "📦",
    EventType.ORDER_DELIVERED: "✅",
    EventType.ORDER_STATUS: "•",
    EventType.COMMENT: "💬",
    EventType.ATTENTION: "⚠️",
    EventType.SHIPMENT_SENT: "🚚",
    EventType.SHIPMENT_UPDATED: "🚚",
    EventType.SHIPPING_COST: "💸",
    EventType.DEPOSIT: "💰",
    EventType.ADJUSTMENT: "⚖️",
    EventType.RATE: "💱",
}


def notification(event: Event) -> str:
    """A private-chat notification: the same client-safe text as the bell."""
    icon = EVENT_ICONS.get(event.type, "🔔") if event.type else "🔔"
    lines = [f"{icon} <b>{e(event.title)}</b>"]
    if event.body:
        lines.append(e(event.body))
    if event.amount_krw:
        lines.append(f"Баланс: <b>{format_krw(event.amount_krw, signed=True)}</b>")
    return "\n".join(lines)


def notify_settings(settings: NotificationSettings, client_has_telegram: bool) -> str:
    lines = [
        "<b>Уведомления в Telegram</b>",
        f"Кому: {RECIPIENT_LABELS[settings.recipient]}",
        f"Что: {LEVEL_LABELS[settings.level]}",
    ]
    if settings.recipient is NotifyRecipient.CLIENT and not client_has_telegram:
        lines.append("⚠️ У клиента не указан Telegram ID — отправлять некому.")
    if settings.has_recent_error and settings.last_error:
        lines.append(f"⚠️ Последняя отправка не удалась: {e(settings.last_error)}")
    lines.append(
        "\n/notify off — выключить\n/notify me — только мне (проверка)\n"
        "/notify client — клиенту\n/notify important | all — только важные или все"
    )
    return "\n".join(lines)


INTAKE_FAILED = "⚠️ Не получилось принять это фото. Отправьте его, пожалуйста, ещё раз."

GROUP_WELCOME = (
    "👋 Я принимаю заказы.\n"
    "Отправьте фото товара, в подписи — размер (и ссылку, если есть). "
    "На каждое фото создам заказ и отвечу его номером."
)


def intake_accepted(order: Order, audience: Role) -> str:
    """Reply to the photo. `audience` is who can read it (see access.audience_for)."""
    view = order_view(order, audience)
    lines = [f"🆕 <b>Заказ {e(order.id)} принят</b>"]
    title = " ".join(part for part in (view["brand"], view["model"]) if part)
    lines.append(e(title) if title else "Модель уточнит администратор")
    lines.append(f"Размер: {e(view['size'])}" if view["size"] else "Размер: не указан")
    if view["client_comment"]:
        lines.append(f"💬 {e(view['client_comment'])}")
    if audience is Role.ADMIN:
        if view["source_url"]:
            lines.append(f"🔒 Ссылка: {e(view['source_url'])}")
        recognition = view.get("recognition") or {}
        if recognition.get("engine"):
            confidence = recognition.get("confidence") or 0
            lines.append(f"🤖 Gemini: уверенность {round(confidence * 100)}%")
        elif recognition.get("error"):
            lines.append(f"🤖 Без распознавания: {e(recognition['error'])}")
        lines.append(f"\nВыкуп: <code>/buy {e(order.id)} закупка цена</code>")
    return "\n".join(lines)


def intake_not_an_order(link: str | None) -> str:
    where = f" {e(link)}" if link else ""
    return (
        f"🤔 Фото от клиента не похоже на заказ — заказ не создан.{where}\n"
        "Если это заказ, ответьте на это фото командой /add."
    )


def group_added_for_admin(title: str, chat_id: int, sees_photos: bool) -> str:
    lines = [
        f"✅ Бот добавлен в группу «{e(title)}».",
        f"ID группы: <code>{chat_id}</code>",
        "Чтобы бот работал только в ней, укажите на сервере "
        f"<code>ALLOWED_CHAT_IDS={chat_id}</code>.",
    ]
    if not sees_photos:
        lines.append(
            "\n⚠️ Бот не видит обычные сообщения группы (Privacy Mode). В @BotFather: "
            "/setprivacy → выберите бота → Disable, затем удалите бота из группы и добавьте "
            "снова. Или сделайте бота администратором группы."
        )
    return "\n".join(lines)


ADMIN_HELP = """<b>Команды администратора</b>
/buy 5 140000 170000 — выкуп: закупка, цена клиенту (списывает баланс один раз)
/cancel 5 — отмена (возвращает списанное один раз; после отправки отмены нет)
/rebuy 5 150000 185000 [ссылка] [причина] — перезаказ в другом магазине (разница по цене)
/status warehouse 5 7 12 — статус нескольких заказов (warehouse, cargo, delivered)
/cargo TRACK123 5 10 18 — отправка: создаёт shipment, ставит статус «Отправлен»
/shipcost 1 95000 — стоимость доставки отправки #1 (списывается с баланса)
/order 5 — карточка заказа
/shipments, /shipment SHP-2026-001 — отправки
/balance, /history — баланс и история
/deposit 5000000 [комментарий] — пополнение
/adjust -15000 причина — корректировка (комментарий увидит клиент)
/rate 1350 — курс KRW за 1 USD
/notify — уведомления в личку (выкл / мне / клиенту; важные / все)
/add — ответом на фото: принять его как заказ
Фото товара в личку боту (или пересланное) — новый заказ
/whoami — ваш Telegram ID"""

CLIENT_HELP = """<b>Новый заказ</b> — фото товара, в подписи размер (и ссылка, если есть).

<b>Команды</b>
/balance — баланс в ₩ и $
/history — история баланса
/order 125 — карточка заказа
/shipments — отправки
/whoami — ваш Telegram ID"""

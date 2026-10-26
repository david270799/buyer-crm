"""The client's two buttons under the message field (the owner, 26.10.2026).

«💰 Баланс» sends the balance picture (the same as «Отправить баланс» in the
Mini App) with the balance in the caption. «📦 Получил посылку» sends the
pictures of the shipments in transit, asks which one arrived, then shows that
parcel again with a checklist of its orders: the ticked ones become «Доставлен»;
what did not arrive stays «Отправлен», gets «Требует внимания» and the admins
get a message. No money moves.

The checklist keeps no state on the server: the ticks travel in the callback
data as a bitmask (rcv:t:{shipment}:{mask}:{index}).
"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from crm.bot import formatting as fmt
from crm.bot.access import HasRole
from crm.domain.enums import OrderStatus, Role
from crm.domain.errors import CRMError
from crm.domain.models import Order, Shipment
from crm.domain.size_label import size_text
from crm.domain.views import ledger_rows
from crm.services.common import Actor
from crm.services.container import Services
from crm.services.share_pictures import (
    balance_picture,
    goods_word,
    shipment_picture,
    since_last_deposit,
)

logger = logging.getLogger(__name__)

BALANCE_BUTTON = "💰 Баланс"
PARCEL_BUTTON = "📦 Получил посылку"
# «💰 Баланс» is hidden for now (the owner, 26.10.2026: «скрой, потом скажу»);
# the handler stays, set True to show the button again.
SHOW_BALANCE_BUTTON = False
CLIENT_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BALANCE_BUTTON), KeyboardButton(text=PARCEL_BUTTON)]
        if SHOW_BALANCE_BUTTON
        else [KeyboardButton(text=PARCEL_BUTTON)]
    ],
    resize_keyboard=True,
    is_persistent=True,
)
OPEN = "rcv:o:"  # rcv:o:{shipment}
TOGGLE = "rcv:t:"  # rcv:t:{shipment}:{mask}:{index}
ALL = "rcv:a:"  # rcv:a:{shipment}
DONE = "rcv:d:"  # rcv:d:{shipment}:{mask}
MAX_ORDERS = 60  # a bitmask in base 36 still fits Telegram's 64-byte callback data


# --- data -----------------------------------------------------------------------


def _in_transit(services: Services, actor: Actor) -> list[tuple[Shipment, list[Order]]]:
    """Shipments still «В пути» with their orders that are «Отправлен»."""
    shipments = services.shipments.list_shipments(actor, limit=50)
    done = services.shipments.delivered_ids(shipments)
    found = []
    for shipment in shipments:
        if shipment.id in done:
            continue
        _, orders = services.shipments.get_shipment(actor, shipment.id)
        waiting = [o for o in orders if o.status is OrderStatus.CARGO]
        if waiting:
            found.append((shipment, orders))
    return found


def _waiting(orders: list[Order]) -> list[Order]:
    return [o for o in orders if o.status is OrderStatus.CARGO][:MAX_ORDERS]


def _balance_photo(services: Services, actor: Actor) -> tuple[bytes, str]:
    view = services.finance.get_balance(actor)
    entries = services.finance.history(actor, 50)
    rows = ledger_rows(entries, actor.role or Role.CLIENT)
    orders = services.orders.get_orders(actor, [r["order_id"] for r in rows if r["order_id"]])
    shipments = {}
    for row in rows:
        sid = row.get("shipment_id")
        if sid and sid not in shipments:
            with contextlib.suppress(CRMError):
                found, _ = services.shipments.get_shipment(actor, sid)
                shipments[sid] = {
                    "tracking_code": found.tracking_code,
                    "thumbnail_url": found.thumbnail_url or found.photo_url,
                }
    for row in rows:
        order = orders.get(row["order_id"]) if row["order_id"] else None
        row["order"] = (
            {"title": order.title, "thumbnail_url": order.thumbnail_url} if order else None
        )
        row["shipment"] = shipments.get(row.get("shipment_id") or "")
    picture = balance_picture(
        view.balance_krw,
        view.krw_per_usd,
        view.balance_usd,
        since_last_deposit(rows),
        _reader(services),
        datetime.now(UTC),
    )
    return picture, fmt.balance(view)


def _reader(services: Services):
    images = services.images
    return (lambda url: images.read(url)) if images is not None else (lambda url: None)


def _shipment_photo(services: Services, shipment: Shipment, orders: list[Order]) -> bytes:
    return shipment_picture(shipment, orders, _reader(services))


# --- texts and keyboards ------------------------------------------------------------


def _short(shipment: Shipment, orders: list[Order]) -> str:
    when = shipment.shipment_date or shipment.created_at
    date = f"{when.day:02d}.{when.month:02d}" if when else ""
    code = shipment.tracking_code or (
        f"#{shipment.shipment_number}" if shipment.shipment_number else shipment.id
    )
    return " · ".join(p for p in (code, date, f"{len(orders)} {goods_word(len(orders))}") if p)


def _order_line(order: Order) -> str:
    parts = [
        order.id,
        " ".join(p for p in (order.brand, order.model) if p) or None,
        size_text(order.size, order.size_kr),
    ]
    return " · ".join(p for p in parts if p)


def checklist(shipment: Shipment, waiting: list[Order], mask: int) -> InlineKeyboardMarkup:
    rows = []
    for index, order in enumerate(waiting):
        ticked = bool(mask >> index & 1)
        text = f"{'☑' if ticked else '☐'} {_order_line(order)}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=text[:60], callback_data=f"{TOGGLE}{shipment.id}:{_b36(mask)}:{index}"
                )
            ]
        )
    count = bin(mask).count("1")
    rows.append(
        [
            InlineKeyboardButton(text="✅ Выбрать все", callback_data=f"{ALL}{shipment.id}"),
            InlineKeyboardButton(
                text=f"📥 Получено ({count})", callback_data=f"{DONE}{shipment.id}:{_b36(mask)}"
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _b36(value: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        value, rest = divmod(value, 36)
        out = digits[rest] + out
        if not value:
            return out


def _caption(shipment: Shipment, waiting: list[Order]) -> str:
    code = fmt.e(shipment.tracking_code or shipment.id)
    count = f"{len(waiting)} {goods_word(len(waiting))}"
    return f"📦 <b>{code}</b> · {count}\nОтметьте, что пришло, и нажмите «Получено»."


def admin_report(
    shipment: Shipment, orders: list[Order], delivered: list[str], missing: list[str]
) -> str:
    by_id = {o.id: o for o in orders}
    code = fmt.e(shipment.tracking_code or shipment.id)
    lines = [f"⚠️ <b>Клиент получил не всё</b> из посылки <b>{code}</b>:"]
    lines += [f"✅ {fmt.e(_order_line(by_id[i]))}" for i in delivered if i in by_id]
    lines += [
        f"❌ <b>{fmt.e(_order_line(by_id[i]))} — не пришёл</b>" for i in missing if i in by_id
    ]
    lines.append("Эти заказы остались «Отправлен» и отмечены «Требует внимания».")
    return "\n".join(lines)


# --- handlers ---------------------------------------------------------------------


async def on_balance(message: Message, services: Services, actor: Actor) -> None:
    picture, caption = await asyncio.to_thread(_balance_photo, services, actor)
    await message.answer_photo(
        BufferedInputFile(picture, "balance.png"), caption=caption, reply_markup=CLIENT_KEYBOARD
    )


async def on_parcel(message: Message, services: Services, actor: Actor) -> None:
    found = await asyncio.to_thread(_in_transit, services, actor)
    if not found:
        await message.answer(
            "Сейчас посылок в пути нет — всё уже доставлено 👍", reply_markup=CLIENT_KEYBOARD
        )
        return
    pictures = await asyncio.to_thread(lambda: [_shipment_photo(services, s, o) for s, o in found])
    files = [BufferedInputFile(p, f"{s.id}.png") for p, (s, _) in zip(pictures, found, strict=True)]
    if len(files) == 1:
        await message.answer_photo(files[0], caption="📦 Посылка в пути: 1")
    else:
        for start in range(0, len(files), 10):  # an album holds up to 10 photos
            chunk = files[start : start + 10]
            media = [InputMediaPhoto(media=f) for f in chunk]
            if start == 0:
                media[0] = InputMediaPhoto(
                    media=chunk[0], caption=f"📦 Посылки в пути: {len(files)}"
                )
            await message.answer_media_group(media)
    buttons = [
        [InlineKeyboardButton(text=_short(s, _waiting(o))[:60], callback_data=f"{OPEN}{s.id}")]
        for s, o in found
    ]
    await message.answer(
        "Какая посылка пришла?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


async def _load(services: Services, actor: Actor, shipment_id: str) -> tuple[Shipment, list[Order]]:
    return await asyncio.to_thread(services.shipments.get_shipment, actor, shipment_id)


async def on_open(call: CallbackQuery, services: Services, actor: Actor) -> None:
    shipment_id = call.data.removeprefix(OPEN)
    shipment, orders = await _load(services, actor, shipment_id)
    waiting = _waiting(orders)
    await call.answer()
    if not waiting:
        await call.message.answer("Эта посылка уже отмечена как полученная ✅")
        return
    picture = await asyncio.to_thread(_shipment_photo, services, shipment, orders)
    await call.message.answer_photo(
        BufferedInputFile(picture, f"{shipment.id}.png"),
        caption=_caption(shipment, waiting),
        reply_markup=checklist(shipment, waiting, 0),
    )


async def _redraw(call: CallbackQuery, shipment: Shipment, waiting: list[Order], mask: int) -> None:
    with contextlib.suppress(Exception):  # «message is not modified» on a double tap
        await call.message.edit_reply_markup(reply_markup=checklist(shipment, waiting, mask))
    await call.answer()


async def on_toggle(call: CallbackQuery, services: Services, actor: Actor) -> None:
    shipment_id, mask, index = call.data.removeprefix(TOGGLE).rsplit(":", 2)
    shipment, orders = await _load(services, actor, shipment_id)
    await _redraw(call, shipment, _waiting(orders), int(mask, 36) ^ (1 << int(index)))


async def on_all(call: CallbackQuery, services: Services, actor: Actor) -> None:
    shipment, orders = await _load(services, actor, call.data.removeprefix(ALL))
    waiting = _waiting(orders)
    await _redraw(call, shipment, waiting, (1 << len(waiting)) - 1)


async def on_done(call: CallbackQuery, services: Services, actor: Actor, bot: Bot) -> None:
    shipment_id, mask_text = call.data.removeprefix(DONE).rsplit(":", 1)
    shipment, orders = await _load(services, actor, shipment_id)
    waiting = _waiting(orders)
    mask = int(mask_text, 36)
    if not waiting:
        await call.answer("Уже отмечено ✅", show_alert=False)
        return
    if mask == 0:
        await call.answer("Отметьте, что пришло (или «Выбрать все»)", show_alert=True)
        return
    received = [o.id for i, o in enumerate(waiting) if mask >> i & 1]
    result = await asyncio.to_thread(services.orders.client_received, actor, shipment.id, received)
    await call.answer()
    with contextlib.suppress(Exception):
        await call.message.edit_reply_markup(reply_markup=None)
    code = fmt.e(shipment.tracking_code or shipment.id)
    if not result.missing:
        await call.message.answer(
            f"✅ Спасибо! Посылка <b>{code}</b> получена полностью.\n"
            f"{fmt.e(', '.join(result.delivered))} — «Доставлен».",
            reply_markup=CLIENT_KEYBOARD,
        )
        return
    missing_lines = ", ".join(_order_line(o) for o in waiting if o.id in result.missing)
    await call.message.answer(
        f"📥 Отмечено: получено <b>{len(result.delivered)} из {len(waiting)}</b>"
        + (f" ({fmt.e(', '.join(result.delivered))})" if result.delivered else "")
        + f".\nПро {fmt.e(missing_lines)} мы уже знаем и разберёмся.",
        reply_markup=CLIENT_KEYBOARD,
    )
    # The admins get the parcel picture and what is missing.
    picture = await asyncio.to_thread(_shipment_photo, services, shipment, orders)
    text = admin_report(shipment, orders, result.delivered, result.missing)
    for admin_id in services.roles.admin_ids:
        try:
            await bot.send_photo(
                admin_id, BufferedInputFile(picture, f"{shipment.id}.png"), caption=text[:1024]
            )
        except Exception:  # noqa: BLE001 - an admin who never opened the bot
            logger.warning("Could not tell admin %s about a missing parcel item", admin_id)


def build() -> Router:
    router = Router(name="client_buttons")
    private = F.chat.type == ChatType.PRIVATE
    client = HasRole(Role.CLIENT, Role.ADMIN)  # the admin can try it too
    router.message.register(on_balance, private, client, F.text == BALANCE_BUTTON)
    router.message.register(on_parcel, private, client, F.text == PARCEL_BUTTON)
    router.callback_query.register(on_open, client, F.data.startswith(OPEN))
    router.callback_query.register(on_toggle, client, F.data.startswith(TOGGLE))
    router.callback_query.register(on_all, client, F.data.startswith(ALL))
    router.callback_query.register(on_done, client, F.data.startswith(DONE))
    return router

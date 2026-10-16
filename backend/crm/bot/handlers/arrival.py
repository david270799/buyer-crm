"""«📦 Пришло на склад» in the admin's private chat (the owner, 16.10.2026).

The button (under /start, or /arrived) lists the bought orders; the admin taps
one and sends a photo of what arrived — or simply sends a photo with «N5» as the
caption. Gemini checks the size on the label against the order (not for
watches) and writes a short Korean review; the order becomes «На складе».
"""

import asyncio
import logging
import re
import time

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, Filter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from crm.bot import formatting as fmt
from crm.bot.access import HasRole
from crm.bot.handlers.intake import _file_id
from crm.domain.enums import Role
from crm.domain.errors import CRMError
from crm.domain.ids import normalize_order_id
from crm.services.arrival import MATCH, MISMATCH, UNCLEAR, ArrivalResult
from crm.services.common import Actor
from crm.services.container import Services
from crm.services.image_service import ORDER_PHOTOS_FOLDER, process_image

logger = logging.getLogger(__name__)

LIST = "arr:list"
PICK = "arr:"
WAIT_SECONDS = 15 * 60
# «N5», «n 5», «#5», «№5», Cyrillic «Н5»: a bare «42» stays a size of a new order.
_ORDER_CAPTION = re.compile(r"^\s*[NnНн#№]\s*(\d{1,6})\s*$")

ARRIVAL_BUTTON = InlineKeyboardButton(text="📦 Пришло на склад", callback_data=LIST)


def caption_order(text: str | None) -> str | None:
    match = _ORDER_CAPTION.match(text or "")
    return f"N{int(match.group(1))}" if match else None


def result_text(result: ArrivalResult) -> str:
    order = result.order
    head = f"<b>{fmt.e(order.id)}</b> · {fmt.e(order.title or 'товар')}"
    lines = [head]
    lines.append("🏠 Статус: «На складе»" if result.moved_to_warehouse else "Фото сохранено")
    ordered = fmt.e(order.size or "—")
    seen = fmt.e(result.size_seen or "—")
    if result.status == MATCH:
        lines.append(f"✅ Размер совпадает: {seen}")
    elif result.status == MISMATCH:
        lines.append(f"⚠️ <b>Размер не тот!</b> На фото {seen}, заказан {ordered}")
    elif result.status == UNCLEAR:
        lines.append(f"❓ Размер на фото не прочитан точно (видно: {seen}, заказан {ordered})")
    elif order.category == "watch":
        lines.append("⌚ Часы — размер не проверяется")
    elif not order.size:
        lines.append("Размер в заказе не указан — не с чем сравнить")
    if result.note:
        lines.append(f"📝 {fmt.e(result.note)}")
    if result.error:
        lines.append(f"Gemini: {fmt.e(result.error)}")
    if result.review_ko:
        lines.append(
            f"\n💬 Отзыв (нажмите, чтобы скопировать):\n<code>{fmt.e(result.review_ko)}</code>"
        )
    return "\n".join(lines)


def build(services: Services) -> Router:
    router = Router(name="arrival")
    waiting_for: dict[int, tuple[str, float]] = {}  # admin id → (order id, since)

    def pending(user_id: int) -> str | None:
        found = waiting_for.get(user_id)
        if found and time.monotonic() - found[1] < WAIT_SECONDS:
            return found[0]
        waiting_for.pop(user_id, None)
        return None

    def is_arrival(message: Message, role: Role | None) -> bool:
        if role is not Role.ADMIN or message.chat.type != ChatType.PRIVATE:
            return False
        if message.from_user is None or _file_id(message) is None:
            return False
        return bool(caption_order(message.caption) or pending(message.from_user.id))

    async def show_list(target: Message, actor: Actor) -> None:
        if services.arrival is None:
            return
        orders = await asyncio.to_thread(services.arrival.waiting, actor)
        if not orders:
            await target.answer("Выкупленных заказов, которые ждут склада, нет.")
            return
        buttons = [
            InlineKeyboardButton(
                text=f"{o.id} · {(o.title or 'товар')[:18]}{f' · {o.size}' if o.size else ''}",
                callback_data=f"{PICK}{o.id}",
            )
            for o in orders
        ]
        rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
        await target.answer(
            "Какой заказ пришёл? Выберите номер — или просто пришлите фото с подписью «N5».",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )

    async def on_command(message: Message, actor: Actor | None) -> None:
        if actor is not None and message.chat.type == ChatType.PRIVATE:
            await show_list(message, actor)

    async def on_list(query: CallbackQuery, actor: Actor | None) -> None:
        await query.answer()
        if actor is not None and isinstance(query.message, Message):
            await show_list(query.message, actor)

    async def on_pick(query: CallbackQuery) -> None:
        order_id = normalize_order_id((query.data or "")[len(PICK) :])
        waiting_for[query.from_user.id] = (order_id, time.monotonic())
        await query.answer()
        if isinstance(query.message, Message):
            await query.message.answer(
                f"Пришлите фото <b>{fmt.e(order_id)}</b> со склада: "
                "этикетку с размером или сам товар."
            )

    async def on_photo(message: Message, bot: Bot, actor: Actor | None) -> None:
        if actor is None or services.arrival is None or message.from_user is None:
            return
        order_id = caption_order(message.caption) or pending(message.from_user.id)
        assert order_id is not None
        waiting_for.pop(message.from_user.id, None)
        wait = await message.answer(f"Проверяю {fmt.e(order_id)}…")
        try:
            buffer = await bot.download(_file_id(message))
            main, thumb, size = await asyncio.to_thread(
                process_image, buffer.read() if buffer else b""
            )
            photo = None
            if services.images is not None:
                photo = await asyncio.to_thread(
                    services.images.store_processed, main, thumb, size, folder=ORDER_PHOTOS_FOLDER
                )
            result = await asyncio.to_thread(
                services.arrival.record,
                actor,
                order_id,
                main,
                photo.photo_url if photo else None,
                photo.thumbnail_url if photo else None,
            )
        except CRMError as exc:
            await bot.edit_message_text(
                fmt.e(exc.user_message), chat_id=wait.chat.id, message_id=wait.message_id
            )
            return
        await bot.edit_message_text(
            result_text(result),
            chat_id=wait.chat.id,
            message_id=wait.message_id,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[ARRIVAL_BUTTON]]),
        )

    router.message.register(on_command, Command("arrived"), HasRole(Role.ADMIN))
    router.callback_query.register(on_list, F.data == LIST, HasRole(Role.ADMIN))
    router.callback_query.register(on_pick, F.data.startswith(PICK), HasRole(Role.ADMIN))
    router.message.register(on_photo, _ArrivalFilter(is_arrival))
    return router


class _ArrivalFilter(Filter):
    """Only arrival photos; everything else goes on to the order intake."""

    def __init__(self, check):
        self._check = check

    async def __call__(self, message: Message, role: Role | None = None) -> bool:
        return self._check(message, role)

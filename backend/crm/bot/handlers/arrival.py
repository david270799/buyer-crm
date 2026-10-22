"""«📦 Пришло на склад» in the admin's private chat (the owner, 16.10.2026).

The button (under /start, or /arrived) lists the bought orders; the admin taps
one and sends a photo of what arrived — or simply sends a photo with «N5» as the
caption. Any other photo the admin sends privately makes the bot ask which order
it is (or «➕ Это новый заказ», the old behaviour). Gemini checks the size on the
label against the order and writes a short Korean review (watches: the photo is
only saved); the order becomes «На складе».
"""

import asyncio
import contextlib
import itertools
import logging
import re
import time
from dataclasses import dataclass, field

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, Filter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from crm.bot import formatting as fmt
from crm.bot.access import HasRole
from crm.bot.handlers.intake import PhotoIntake, _file_id
from crm.config import Settings
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
PHOTO_PICK = "arp:"  # «this photo is order N5»: arp:{token}:{order}
PHOTO_NEW = "arn:"  # «this photo is a new order»
WAIT_SECONDS = 15 * 60
SERIES_SECONDS = 30
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
    ordered = fmt.e(" / ".join(s for s in (order.size, order.size_kr) if s) or "—")
    seen = fmt.e(result.size_seen or "—")
    if result.status == MATCH:
        lines.append(f"✅ Размер совпадает: {seen}")
    elif result.status == MISMATCH:
        lines.append(f"⚠️ <b>Размер не тот!</b> На фото {seen}, заказан {ordered}")
    elif result.status == UNCLEAR:
        lines.append(f"❓ Размер на фото не прочитан точно (видно: {seen}, заказан {ordered})")
    elif order.category == "watch":
        lines.append("⌚ Часы — фото сохранено, проверка не нужна")
    elif not (order.size or order.size_kr):
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


def build(services: Services, settings: Settings) -> Router:
    router = Router(name="arrival")
    waiting_for: dict[int, tuple[str, float]] = {}  # admin id → (order id, since)
    # Photos the admin sent without saying which order: token → (messages, last photo at).
    asked: dict[str, tuple[list[Message], float]] = {}
    asked_by: dict[int, str] = {}  # admin id → their open question
    # Photos within SERIES_SECONDS of the last one belong to the same order: the
    # first is checked by Gemini, the rest only go to the card (owner, 20.10.2026).
    series: dict[int, _Series] = {}
    tokens = itertools.count(1)
    new_orders = PhotoIntake(services, settings)

    def pending(user_id: int) -> str | None:
        found = waiting_for.get(user_id)
        if found and time.monotonic() - found[1] < WAIT_SECONDS:
            return found[0]
        waiting_for.pop(user_id, None)
        return None

    def is_admin_photo(message: Message, role: Role | None) -> bool:
        """Every photo the admin sends the bot privately: the bot asks which order
        it is (owner, 16.10.2026), «N5» in the caption answers at once."""
        if role is not Role.ADMIN or message.chat.type != ChatType.PRIVATE:
            return False
        if message.from_user is None or message.reply_to_message is not None:
            return False
        return _file_id(message) is not None

    def order_buttons(orders, prefix: str) -> list[list[InlineKeyboardButton]]:
        buttons = [
            InlineKeyboardButton(
                text=f"{o.id} · {(o.title or 'товар')[:18]}{f' · {o.size}' if o.size else ''}",
                callback_data=f"{prefix}{o.id}",
            )
            for o in orders
        ]
        return [buttons[i : i + 2] for i in range(0, len(buttons), 2)]

    async def show_list(target: Message, actor: Actor) -> None:
        if services.arrival is None:
            return
        orders = await asyncio.to_thread(services.arrival.waiting, actor)
        if not orders:
            await target.answer("Выкупленных заказов, которые ждут склада, нет.")
            return
        await target.answer(
            "Какой заказ пришёл? Выберите номер — или просто пришлите фото с подписью «N5».",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=order_buttons(orders, PICK)),
        )

    async def ask_which(message: Message, actor: Actor) -> None:
        now = time.monotonic()
        for key, (_, since) in list(asked.items()):
            if now - since > WAIT_SECONDS:
                del asked[key]
        token = str(next(tokens))
        asked[token] = ([message], now)
        if message.from_user is not None:
            asked_by[message.from_user.id] = token
        orders = (
            await asyncio.to_thread(services.arrival.waiting, actor) if services.arrival else []
        )
        rows = order_buttons(orders, f"{PHOTO_PICK}{token}:")
        rows.append(
            [InlineKeyboardButton(text="➕ Это новый заказ", callback_data=f"{PHOTO_NEW}{token}")]
        )
        await message.reply(
            "Какой это заказ? Выберите — бот сверит фото с заказом."
            if orders
            else "Выкупленных заказов, которые ждут склада, нет. Это новый заказ?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )

    async def store(bot: Bot, message: Message):
        buffer = await bot.download(_file_id(message))
        main, thumb, size = await asyncio.to_thread(process_image, buffer.read() if buffer else b"")
        photo = None
        if services.images is not None:
            photo = await asyncio.to_thread(
                services.images.store_processed, main, thumb, size, folder=ORDER_PHOTOS_FOLDER
            )
        return main, photo

    async def add_extras(bot: Bot, actor: Actor, run: _Series, messages: list[Message]) -> int:
        """Store more photos of the series and put them on the card; → how many in total."""
        photos = []
        for message in messages:
            try:
                _, photo = await store(bot, message)
            except Exception:  # noqa: BLE001 - one bad photo must not lose the others
                logger.warning("Could not store an extra warehouse photo", exc_info=True)
                continue
            if photo is not None:
                photos.append({"photo_url": photo.photo_url, "thumbnail_url": photo.thumbnail_url})
        if not photos or services.arrival is None:
            return 0
        order = await asyncio.to_thread(services.arrival.add_photos, actor, run.order_id, photos)
        return len(order.arrival_photos)

    def start_series(user_id: int, order_id: str) -> _Series:
        run = _Series(order_id=order_id, last=time.monotonic())
        series[user_id] = run
        return run

    async def check(
        bot: Bot,
        message: Message,
        actor: Actor,
        order_id: str,
        run: _Series,
    ) -> None:
        if services.arrival is None:
            return
        wait = await message.answer(f"Проверяю {fmt.e(order_id)}…")
        try:
            main, photo = await store(bot, message)
            result = await asyncio.to_thread(
                services.arrival.record,
                actor,
                order_id,
                main,
                photo.photo_url if photo else None,
                photo.thumbnail_url if photo else None,
            )
        except CRMError as exc:
            run.failed = True
            await bot.edit_message_text(
                fmt.e(exc.user_message), chat_id=wait.chat.id, message_id=wait.message_id
            )
            return
        run.done = True  # photos arriving from now on go straight to the card
        waiting, run.pending = run.pending, []
        extra = await add_extras(bot, actor, run, waiting) if waiting else 0
        text = result_text(result)
        if extra:
            text += f"\n📷 Ещё фото в карточке: {extra}"
        await bot.edit_message_text(
            text,
            chat_id=wait.chat.id,
            message_id=wait.message_id,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[ARRIVAL_BUTTON]]),
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

    async def on_photo_pick(query: CallbackQuery, bot: Bot, actor: Actor | None) -> None:
        token, _, order_id = (query.data or "")[len(PHOTO_PICK) :].partition(":")
        found = asked.pop(token, None)
        await query.answer()
        if actor is None or not isinstance(query.message, Message):
            return
        with contextlib.suppress(Exception):
            await query.message.edit_reply_markup(reply_markup=None)
        if found is None:
            await query.message.answer("Фото устарело — пришлите его ещё раз.")
            return
        first, *rest = found[0]
        run = start_series(query.from_user.id, normalize_order_id(order_id))
        run.pending.extend(rest)
        await check(bot, first, actor, run.order_id, run)

    async def on_photo_new(query: CallbackQuery, bot: Bot, actor: Actor | None) -> None:
        found = asked.pop((query.data or "")[len(PHOTO_NEW) :], None)
        await query.answer()
        if actor is None or not isinstance(query.message, Message):
            return
        with contextlib.suppress(Exception):
            await query.message.edit_reply_markup(reply_markup=None)
        if found is None:
            await query.message.answer("Фото устарело — пришлите его ещё раз.")
            return
        for message in found[0]:  # each photo of the series is its own new order
            await new_orders.handle(bot, message, actor)

    async def on_photo(message: Message, bot: Bot, actor: Actor | None) -> None:
        if actor is None or message.from_user is None:
            return
        user_id, now = message.from_user.id, time.monotonic()
        order_id = caption_order(message.caption)
        if order_id is None:
            run = series.get(user_id)
            if run is not None and not run.failed and now - run.last < SERIES_SECONDS:
                run.last = now  # one more photo of the same parcel
                if not run.done:
                    run.pending.append(message)  # added right after the check
                    return
                total = await add_extras(bot, actor, run, [message])
                if total:
                    await message.reply(
                        f"📷 Фото добавлено к {fmt.e(run.order_id)} (ещё фото: {total})"
                    )
                return
            token = asked_by.get(user_id)
            open_question = asked.get(token) if token else None
            if open_question and now - open_question[1] < SERIES_SECONDS:
                open_question[0].append(message)  # the same question covers it
                asked[token] = (open_question[0], now)
                return
            order_id = pending(user_id)
        if order_id is None:
            await ask_which(message, actor)
            return
        waiting_for.pop(user_id, None)
        await check(bot, message, actor, order_id, start_series(user_id, order_id))

    router.message.register(on_command, Command("arrived"), HasRole(Role.ADMIN))
    router.callback_query.register(on_list, F.data == LIST, HasRole(Role.ADMIN))
    router.callback_query.register(
        on_photo_pick, F.data.startswith(PHOTO_PICK), HasRole(Role.ADMIN)
    )
    router.callback_query.register(on_photo_new, F.data.startswith(PHOTO_NEW), HasRole(Role.ADMIN))
    router.callback_query.register(on_pick, F.data.startswith(PICK), HasRole(Role.ADMIN))
    router.message.register(on_photo, _ArrivalFilter(is_admin_photo))
    return router


@dataclass
class _Series:
    order_id: str
    last: float
    done: bool = False  # the first photo is checked and saved
    failed: bool = False
    pending: list[Message] = field(default_factory=list)


class _ArrivalFilter(Filter):
    """Only arrival photos; everything else goes on to the order intake."""

    def __init__(self, check):
        self._check = check

    async def __call__(self, message: Message, role: Role | None = None) -> bool:
        return self._check(message, role)

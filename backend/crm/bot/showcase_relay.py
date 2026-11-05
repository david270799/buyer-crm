"""Sends «Витрина» orders (crm.services.showcase_relay): the card's photo with
the size to the orders channel, then «пришёл заказ» to each admin privately.
Wakes after every committed change in this process and every few minutes."""

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup

from crm.bot import formatting as fmt
from crm.bot.admin_group import open_button
from crm.services.image_service import ImageService
from crm.services.showcase_relay import PENDING, RelayTask, ShowcaseRelayService

logger = logging.getLogger(__name__)


def channel_caption(task: RelayTask) -> str:
    lines = [fmt.e(task.title)]
    if task.size_line:
        lines.append(f"Размер: <b>{fmt.e(task.size_line)}</b>")
    return "\n".join(lines)


def admin_text(task: RelayTask, channel_note: str | None) -> str:
    lines = [f"🛍 <b>Заказ из витрины · {fmt.e(task.order_id)}</b>", fmt.e(task.title)]
    if task.size_line:
        lines.append(f"Размер: <b>{fmt.e(task.size_line)}</b>")
    if task.client_price:
        lines.append(f"Цена: ₩ {task.client_price:,}")
    lines.append("Заказал клиент." if task.by_client else "Заказ оформлен из вашей Mini App.")
    if channel_note:
        lines.append(channel_note)
    return "\n".join(lines)


class ShowcaseRelay:
    def __init__(
        self,
        bot: Bot,
        service: ShowcaseRelayService,
        images: ImageService | None,
        admin_ids: frozenset[int],
        mini_app_url: str | None,
        *,
        poll_seconds: float = 300,
        settle_seconds: float = 1.0,
    ):
        self._bot = bot
        self._service = service
        self._images = images
        self._admins = admin_ids
        self._mini_app = mini_app_url
        self._poll = poll_seconds
        self._settle = settle_seconds
        self._notes: dict[str, str | None] = {}

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        wake = asyncio.Event()

        def poke() -> None:
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                pass  # the loop is shutting down

        self._service.listen(poke)
        try:
            while True:
                wake.clear()
                await self.run_once()
                try:
                    await asyncio.wait_for(wake.wait(), timeout=self._poll)
                except TimeoutError:
                    continue
                await asyncio.sleep(self._settle)
        finally:
            self._service.unlisten(poke)

    async def run_once(self) -> int:
        try:
            tasks = await asyncio.to_thread(self._service.pending)
        except Exception:  # noqa: BLE001 - storage hiccup: next round
            logger.warning("Could not read showcase orders to send", exc_info=True)
            return 0
        done = 0
        for task in tasks:
            try:
                if task.state == PENDING:
                    await self._post(task)
                await self._tell_admins(task)
            except _TryLater:
                break
            await asyncio.to_thread(self._service.sent, task.order_id)
            self._notes.pop(task.order_id, None)
            done += 1
        return done

    def _photo(self, task: RelayTask) -> BufferedInputFile | None:
        data = self._images.read(task.photo_url) if self._images and task.photo_url else None
        return BufferedInputFile(data, filename=f"{task.order_id}.jpg") if data else None

    async def _post(self, task: RelayTask) -> None:
        chat = await asyncio.to_thread(self._service.orders_chat)
        message_id = None
        if chat is None:
            note = "⚠️ В канал заказов не отправлено: не знаю, какой это канал."
        else:
            photo = await asyncio.to_thread(self._photo, task)
            try:
                if photo is not None:
                    sent = await self._bot.send_photo(chat, photo, caption=channel_caption(task))
                else:
                    sent = await self._bot.send_message(chat, channel_caption(task))
                message_id, note = sent.message_id, "📤 Фото с размером отправлено в канал заказов."
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
                raise _TryLater from None
            except (TelegramBadRequest, TelegramForbiddenError) as exc:
                logger.warning("Showcase order %s not posted to %s: %s", task.order_id, chat, exc)
                note = "⚠️ В канал заказов не отправилось: у бота нет права писать туда."
            except Exception as exc:  # noqa: BLE001 - network: try again later
                logger.warning("Showcase order %s not posted yet: %s", task.order_id, exc)
                raise _TryLater from None
        self._notes[task.order_id] = note
        await asyncio.to_thread(
            self._service.posted, task.order_id, chat if message_id else None, message_id
        )

    async def _tell_admins(self, task: RelayTask) -> None:
        text = admin_text(task, self._notes.get(task.order_id))
        button = await open_button(
            self._bot, self._mini_app, f"order:{task.order_id}", in_group=False
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[[button]]) if button else None
        for admin in sorted(self._admins):
            photo = await asyncio.to_thread(self._photo, task)
            try:
                if photo is not None:
                    await self._bot.send_photo(admin, photo, caption=text, reply_markup=markup)
                else:
                    await self._bot.send_message(admin, text, reply_markup=markup)
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
                raise _TryLater from None
            except (TelegramBadRequest, TelegramForbiddenError) as exc:
                logger.info("Admin %s not told about %s: %s", admin, task.order_id, exc)
            except Exception as exc:  # noqa: BLE001 - network: try again later
                logger.warning("Admin not told about %s yet: %s", task.order_id, exc)
                raise _TryLater from None


class _TryLater(Exception):
    pass

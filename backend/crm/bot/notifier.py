"""Sends pending events to private chats (see crm.domain.notifications).

Runs next to long polling in the bot process. It wakes up as soon as a
transaction with an event commits in this process and, as a safety net for
retries and events written elsewhere, every few minutes. Only one bot process may run
(Telegram allows a single long-polling consumer), so there is one sender.
"""

import asyncio
import logging
from urllib.parse import urlencode, urlsplit, urlunsplit

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    WebAppInfo,
)

from crm.bot import formatting as fmt
from crm.domain.events import Event
from crm.domain.notifications import DeliveryStatus
from crm.services.notifications import NotificationService, SendOutcome

logger = logging.getLogger(__name__)

_MAX_TEXT = 3500
_MAX_ROUNDS = 10
_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def open_url(base: str, event: Event) -> str:
    """Mini App link that opens the order, the shipment or the notifications."""
    if len(event.order_ids) == 1:
        target = f"order:{event.order_ids[0]}"
    elif event.shipment_id:
        target = f"shipment:{event.shipment_id}"
    else:
        target = "notifications"
    parts = urlsplit(base)
    query = "&".join(q for q in (parts.query, urlencode({"open": target})) if q)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", query, ""))


def _explain(exc: Exception) -> tuple[str, bool]:
    """(human-readable reason, permanent?)"""
    text = str(exc)
    if isinstance(exc, TelegramForbiddenError):
        return "получатель не открыл бота или заблокировал его (нужно нажать Start)", True
    if isinstance(exc, TelegramBadRequest):
        if "chat not found" in text.lower():
            return "чат не найден: получатель ещё не открыл бота (нужно нажать Start)", True
        return f"Telegram отклонил сообщение: {text}", True
    return f"нет связи с Telegram: {text}", False


class TelegramNotifier:
    def __init__(
        self,
        bot: Bot,
        notifications: NotificationService,
        mini_app_url: str | None,
        *,
        poll_seconds: float = 300,
        settle_seconds: float = 0.5,
        pause_seconds: float = 0.4,
    ):
        self._bot = bot
        self._service = notifications
        self._mini_app_url = mini_app_url
        self._poll = poll_seconds
        self._settle = settle_seconds
        self._pause = pause_seconds

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        wake = asyncio.Event()

        def poke() -> None:
            # Called from worker threads right after a commit.
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
                # Let the rest of a burst (a few events from one action) arrive.
                await asyncio.sleep(self._settle)
        finally:
            self._service.unlisten(poke)

    async def run_once(self) -> int:
        """Handle everything that is due; returns the number of events sent or failed."""
        handled = 0
        for _ in range(_MAX_ROUNDS):
            try:
                batch = await asyncio.to_thread(self._service.due)
            except Exception:  # noqa: BLE001 - Firestore hiccup: try again later
                logger.warning("Could not read pending notifications", exc_info=True)
                return handled
            retry_later = False
            for delivery in batch.deliveries:
                event = delivery.event
                outcomes = [await self._send(chat_id, event) for chat_id in delivery.chat_ids]
                try:
                    status = await asyncio.to_thread(self._service.record, delivery, outcomes)
                except Exception:  # noqa: BLE001
                    logger.warning("Could not record a notification", exc_info=True)
                    return handled
                handled += 1
                retry_later = retry_later or status is DeliveryStatus.PENDING
            if retry_later or not batch.more:
                break
        return handled

    def _markup(self, event: Event) -> InlineKeyboardMarkup | None:
        if not self._mini_app_url:
            return None
        button = InlineKeyboardButton(
            text="Открыть в CRM", web_app=WebAppInfo(url=open_url(self._mini_app_url, event))
        )
        return InlineKeyboardMarkup(inline_keyboard=[[button]])

    async def _send(self, chat_id: int, event: Event) -> SendOutcome:
        text = fmt.notification(event)[:_MAX_TEXT]
        markup = self._markup(event)
        for attempt in range(2):
            try:
                await self._bot.send_message(
                    chat_id, text, reply_markup=markup, link_preview_options=_NO_PREVIEW
                )
                await asyncio.sleep(self._pause)
                return SendOutcome(chat_id, ok=True)
            except TelegramRetryAfter as exc:
                if attempt == 0:
                    await asyncio.sleep(min(exc.retry_after, 30))
                    continue
                return SendOutcome(chat_id, ok=False, error="Telegram просит подождать")
            except TelegramBadRequest as exc:
                if markup is not None and attempt == 0:
                    # A bad button must not cost the notification itself.
                    logger.warning("Notification with a Mini App button rejected: %s", exc)
                    markup = None
                    continue
                reason, permanent = _explain(exc)
                return SendOutcome(chat_id, ok=False, permanent=permanent, error=reason)
            except Exception as exc:  # noqa: BLE001 - network errors, Telegram 5xx
                reason, permanent = _explain(exc)
                if permanent:
                    logger.warning("Notification to %s not delivered: %s", chat_id, reason)
                return SendOutcome(chat_id, ok=False, permanent=permanent, error=reason)
        return SendOutcome(chat_id, ok=False, error="не удалось отправить")

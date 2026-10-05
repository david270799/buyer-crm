"""Keeps the reaction on each order photo in the group in line with the
order status (see crm.services.reactions). Runs next to the notifier: wakes
after every committed change in this process and every few minutes."""

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import ReactionTypeEmoji

from crm.services.reactions import ReactionService, ReactionTask

logger = logging.getLogger(__name__)


def _unsupported(exc: TelegramBadRequest) -> bool:
    return "REACTION_INVALID" in str(exc) or "REACTION_EMPTY" in str(exc)


class ReactionSyncer:
    def __init__(
        self,
        bot: Bot,
        service: ReactionService,
        *,
        poll_seconds: float = 300,
        settle_seconds: float = 1.0,
        pause_seconds: float = 0.5,
    ):
        self._bot = bot
        self._service = service
        self._poll = poll_seconds
        self._settle = settle_seconds
        self._pause = pause_seconds

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
            logger.warning("Could not read reactions to update", exc_info=True)
            return 0
        done = 0
        for task in tasks:
            try:
                emoji, error = await self._apply(task)
            except _TryLater:
                break
            await asyncio.to_thread(self._service.record, task, emoji, error)
            done += 1
            await asyncio.sleep(self._pause)
        return done

    async def _apply(self, task: ReactionTask) -> tuple[str | None, str | None]:
        """(emoji set, permanent error). Raises _TryLater on network trouble."""
        if not task.candidates:
            error = await self._set(task, [])
            return None, error
        ordered = list(dict.fromkeys([*([task.current] if task.current else []), *task.candidates]))
        ordered = [e for e in ordered if e in task.candidates]
        last_error = None
        for emoji in ordered:
            try:
                await self._call(task, [ReactionTypeEmoji(emoji=emoji)])
                return emoji, None
            except TelegramBadRequest as exc:
                if _unsupported(exc):
                    last_error = f"реакция {emoji} недоступна в этом чате"
                    continue
                return None, f"Telegram отклонил реакцию: {exc}"
            except TelegramForbiddenError as exc:
                return None, f"нет доступа к чату: {exc}"
        logger.info("No allowed reaction for %s: %s", task.key, last_error)
        return None, last_error

    async def _set(self, task: ReactionTask, reaction: list) -> str | None:
        try:
            await self._call(task, reaction)
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            return str(exc)  # message deleted, bot removed: nothing to clear
        return None

    async def _call(self, task: ReactionTask, reaction: list) -> None:
        try:
            await self._bot.set_message_reaction(
                chat_id=task.chat_id, message_id=task.message_id, reaction=reaction
            )
        except TelegramRetryAfter as exc:
            logger.info("Reactions paused for %ss (Telegram flood control)", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
            raise _TryLater from None
        except (TelegramBadRequest, TelegramForbiddenError):
            raise
        except Exception as exc:  # noqa: BLE001 - network: keep it pending
            logger.warning("Could not set a reaction: %s", exc)
            raise _TryLater from None


class _TryLater(Exception):
    pass

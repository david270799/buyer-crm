"""User-facing error replies. Stack traces go to the log, never to the chat."""

import logging

from aiogram.types import ErrorEvent

from crm.domain.errors import CRMError
from crm.storage import TransactionContentionError

logger = logging.getLogger(__name__)

INTERNAL_ERROR_TEXT = "❌ Внутренняя ошибка. Подробности записаны в лог."
CONTENTION_TEXT = (
    "⏳ Данные сейчас изменяются из другого места. Повторите команду — повтор безопасен."
)


def user_text(exc: BaseException) -> str:
    if isinstance(exc, CRMError):
        return f"❌ {exc.user_message}"
    if isinstance(exc, TransactionContentionError):
        return CONTENTION_TEXT
    return INTERNAL_ERROR_TEXT


async def on_error(event: ErrorEvent) -> bool:
    exc = event.exception
    if isinstance(exc, CRMError):
        logger.info("Rejected: %s", exc.user_message)
    else:
        logger.error(
            "Unhandled error while processing update %s", event.update.update_id, exc_info=exc
        )
    message = event.update.message
    if message is not None:
        try:
            await message.answer(user_text(exc))
        except Exception:  # noqa: BLE001 - never let error reporting crash polling
            logger.exception("Failed to send error reply")
    return True

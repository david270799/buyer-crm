from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from crm.bot.handlers.reply import answer
from crm.domain.enums import Role


async def unknown_command(message: Message, role: Role | None) -> None:
    if role is None:
        return
    await answer(message, "Неизвестная команда или нет доступа. Список команд: /help")


def build() -> Router:
    router = Router(name="fallback")
    router.message.register(
        unknown_command, F.chat.type == ChatType.PRIVATE, F.text.startswith("/")
    )
    return router

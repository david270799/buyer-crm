from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from crm.bot import formatting as fmt
from crm.bot.handlers.reply import answer
from crm.domain.enums import Role

_STRANGER_TEXT = "Это закрытая CRM-система.\nВаш Telegram ID: <code>{user_id}</code>"


async def start(message: Message, role: Role | None) -> None:
    if role is Role.ADMIN:
        await answer(message, fmt.ADMIN_HELP)
    elif role is Role.CLIENT:
        await answer(message, fmt.CLIENT_HELP)
    elif message.chat.type == ChatType.PRIVATE and message.from_user:
        await answer(message, _STRANGER_TEXT.format(user_id=message.from_user.id))


async def whoami(message: Message, role: Role | None) -> None:
    if role is None and message.chat.type != ChatType.PRIVATE:
        return
    role_text = {Role.ADMIN: "администратор", Role.CLIENT: "клиент"}.get(role, "нет доступа")
    await answer(
        message,
        f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n"
        f"Chat ID: <code>{message.chat.id}</code>\nРоль: {role_text}",
    )


def build() -> Router:
    router = Router(name="common")
    router.message.register(start, CommandStart())
    router.message.register(start, Command("help"))
    router.message.register(whoami, Command("whoami"), F.from_user)
    return router

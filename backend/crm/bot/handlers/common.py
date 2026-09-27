from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from crm.bot import formatting as fmt
from crm.bot.handlers.reply import answer
from crm.config import Settings
from crm.domain.enums import Role

_STRANGER_TEXT = "Это закрытая CRM-система.\nВаш Telegram ID: <code>{user_id}</code>"


def _open_app_keyboard(settings: Settings | None) -> InlineKeyboardMarkup | None:
    if settings is None or not settings.mini_app_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть CRM", web_app=WebAppInfo(url=settings.mini_app_url)
                )
            ]
        ]
    )


async def start(message: Message, role: Role | None, settings: Settings | None = None) -> None:
    # Web App buttons are allowed only in private chats.
    private = message.chat.type == ChatType.PRIVATE
    keyboard = _open_app_keyboard(settings) if private else None
    if role is Role.ADMIN:
        await message.answer(fmt.ADMIN_HELP, reply_markup=keyboard)
    elif role is Role.CLIENT:
        await message.answer(fmt.CLIENT_HELP, reply_markup=keyboard)
    elif private and message.from_user:
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

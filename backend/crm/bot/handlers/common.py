import asyncio

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from crm.bot import formatting as fmt
from crm.bot.access import HasRole
from crm.bot.handlers.reply import answer, answer_privately
from crm.config import Settings
from crm.domain.enums import Role
from crm.domain.errors import CRMError
from crm.services.common import Actor
from crm.services.container import Services

_STRANGER_TEXT = "Это закрытая CRM-система.\nВаш Telegram ID: <code>{user_id}</code>"
SETCLIENT_USAGE = (
    "Ответьте командой /setclient на любое сообщение самого клиента (не помощника) в группе\n"
    "или укажите ID: <code>/setclient 123456789 Имя</code>"
)


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


async def setclient(
    message: Message, command: CommandObject, services: Services, actor: Actor
) -> None:
    """/setclient in reply to the client's message, or /setclient <id> [имя]."""
    target = message.reply_to_message
    if target is not None and target.from_user is not None and not command.args:
        telegram_id, name = target.from_user.id, target.from_user.full_name
    else:
        parts = (command.args or "").split(maxsplit=1)
        if not parts or not parts[0].isdigit():
            await answer_privately(message, SETCLIENT_USAGE)
            return
        telegram_id, name = int(parts[0]), parts[1] if len(parts) > 1 else None
    try:
        change = await asyncio.to_thread(services.clients.set_client, actor, telegram_id, name)
    except CRMError as exc:
        await answer_privately(message, f"❌ {fmt.e(exc.user_message)}")
        return
    await answer_privately(message, fmt.client_set(change))


def build() -> Router:
    router = Router(name="common")
    router.message.register(start, CommandStart())
    router.message.register(start, Command("help"))
    router.message.register(whoami, Command("whoami"), F.from_user)
    router.message.register(setclient, Command("setclient"), HasRole(Role.ADMIN))
    return router

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


def _groups_text(chats: dict[int, str]) -> str:
    if not chats:
        return "Ограничений нет: бот работает в любой группе, куда его добавил админ."
    lines = ["Бот работает только в группах:"]
    lines += [f" • {fmt.e(title)} (<code>{chat_id}</code>)" for chat_id, title in chats.items()]
    return "\n".join(lines)


async def setgroup(
    message: Message, command: CommandObject, services: Services, actor: Actor
) -> None:
    """/setgroup in a group: the bot works there (and only in the listed groups).
    In the private chat: shows the list. The command is removed from the group."""
    arg = (command.args or "").strip()
    if message.chat.type == ChatType.PRIVATE and arg.lstrip("-").isdigit():
        chat_id = int(arg)
        title = None
        try:
            title = (await message.bot.get_chat(chat_id)).title
        except Exception:  # the bot may not be in the group yet: the ID is enough
            pass
        chats = await asyncio.to_thread(services.groups.add, actor, chat_id, title)
        await answer(
            message,
            f"✅ Группа «{fmt.e(title or chat_id)}» добавлена.\n" + _groups_text(chats),
        )
        return
    if message.chat.type == ChatType.PRIVATE:
        chats = await asyncio.to_thread(services.groups.listing, actor)
        await answer(
            message,
            _groups_text(chats)
            + "\n\nДобавить группу: /setgroup ID (например, /setgroup -1003713143896). "
            "Убрать: /unsetgroup в группе или /unsetgroup ID здесь.",
        )
        return
    chats = await asyncio.to_thread(services.groups.add, actor, message.chat.id, message.chat.title)
    await answer_privately(
        message,
        f"✅ Группа «{fmt.e(message.chat.title or message.chat.id)}» добавлена.\n"
        + _groups_text(chats),
    )


async def unsetgroup(
    message: Message, command: CommandObject, services: Services, actor: Actor
) -> None:
    arg = (command.args or "").strip()
    if message.chat.type != ChatType.PRIVATE:
        chat_id = message.chat.id
    elif arg.lstrip("-").isdigit():
        chat_id = int(arg)
    else:
        await answer(message, "Формат: /unsetgroup в группе или /unsetgroup ID в личке.")
        return
    chats = await asyncio.to_thread(services.groups.remove, actor, chat_id)
    await answer_privately(
        message, f"Группа <code>{chat_id}</code> убрана.\n" + _groups_text(chats)
    )


async def pin(message: Message, command: CommandObject, services: Services, actor: Actor) -> None:
    """/pin — is a Mini App PIN set; /pin off — remove a forgotten PIN.
    A new PIN is set only in the Mini App (the digits never go through a chat)."""
    arg = (command.args or "").strip().lower()
    if arg in ("off", "выкл", "сброс"):
        await asyncio.to_thread(services.security.set_pin, actor, None)
        text = "🔓 PIN для Mini App сброшен. Задать новый: Mini App → Настройки → «PIN-код»."
    else:
        is_set = await asyncio.to_thread(services.security.pin_set, actor)
        text = (
            "🔒 PIN для Mini App включён. Забыли — /pin off сбросит его."
            if is_set
            else "PIN для Mini App не задан. Задать: Mini App → Настройки → «PIN-код»."
        )
    await answer_privately(message, text)


def build() -> Router:
    router = Router(name="common")
    router.message.register(start, CommandStart())
    router.message.register(start, Command("help"))
    router.message.register(whoami, Command("whoami"), F.from_user)
    router.message.register(setclient, Command("setclient"), HasRole(Role.ADMIN))
    router.message.register(pin, Command("pin"), HasRole(Role.ADMIN))
    router.message.register(setgroup, Command("setgroup"), HasRole(Role.ADMIN))
    router.message.register(unsetgroup, Command("unsetgroup"), HasRole(Role.ADMIN))
    return router

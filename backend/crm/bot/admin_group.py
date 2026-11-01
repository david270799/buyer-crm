"""Talking to the admins: the «Уведомления» topic of their group, or private chats.

See crm.services.admin_group. Everything the bot tells the admins goes through
`tell_admins`: with the group's «Уведомления» topic bound it is one message
there, otherwise (or if the group refuses it) one message to each admin.
"""

import logging
from urllib.parse import urlencode, urlsplit, urlunsplit

from aiogram import Bot
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from crm.services.admin_group import NOTIFICATIONS, AdminGroup
from crm.services.container import Services

logger = logging.getLogger(__name__)


def admin_group(services: Services) -> AdminGroup:
    return services.admin_group.current() if services.admin_group is not None else AdminGroup()


def thread_of(message: Message) -> int | None:
    """The topic a message was written in (None outside topics)."""
    return message.message_thread_id if message.is_topic_message else None


def topic_name(message: Message) -> str | None:
    """In a topic every message «replies» to the topic's first service message,
    which carries the topic name."""
    first = message.reply_to_message
    created = first.forum_topic_created if first is not None else None
    return created.name if created is not None else None


def real_reply(message: Message) -> Message | None:
    """The message this one really answers (not the topic's service message)."""
    first = message.reply_to_message
    if first is None or first.forum_topic_created is not None:
        return None
    return first


def in_topic(services: Services, message: Message, kind: str) -> bool:
    return admin_group(services).kind_of(message.chat.id, thread_of(message)) == kind


def is_admin_group(services: Services, chat_id: int) -> bool:
    group = admin_group(services)
    return group.chat_id is not None and group.chat_id == chat_id


async def start_param_url(bot: Bot, target: str) -> str | None:
    """t.me link that opens the Mini App at `target` (order:N5, shipment:…, prep:…).
    Mini App buttons (web_app) work only in private chats, so groups get this
    link; it needs the bot's main Mini App (@BotFather → Bot Settings → Mini App)."""
    try:
        me = await bot.me()
    except Exception:  # noqa: BLE001 - no button rather than no message
        return None
    if not me.username:
        return None
    param = target.replace(":", "-")  # start_param allows only A-Z a-z 0-9 _ -
    return f"https://t.me/{me.username}?{urlencode({'startapp': param})}"


def mini_app_url(base: str, target: str) -> str:
    parts = urlsplit(base)
    query = "&".join(q for q in (parts.query, urlencode({"open": target})) if q)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", query, ""))


async def open_button(
    bot: Bot, base: str | None, target: str, *, in_group: bool, text: str = "Открыть в CRM"
) -> InlineKeyboardButton | None:
    """«Открыть в CRM»: a Mini App button privately, a t.me link in a group."""
    if not base:
        return None
    if not in_group:
        return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=mini_app_url(base, target)))
    url = await start_param_url(bot, target)
    return InlineKeyboardButton(text=text, url=url) if url else None


async def tell_admins(
    bot: Bot,
    services: Services,
    text: str,
    *,
    photo: str | bytes | None = None,
    mini_app: str | None = None,
    target: str | None = None,
    kind: str = NOTIFICATIONS,
) -> bool:
    """Send `text` (and a photo: file_id or ready input) to the admins.
    `target` adds «Открыть в CRM». True when someone got it."""
    group = admin_group(services)
    thread = group.topic(kind)
    if thread is not None and group.chat_id is not None:
        markup = await _markup(bot, mini_app, target, in_group=True)
        if await _send(bot, group.chat_id, text, photo, markup, thread):
            return True
        logger.warning("The admin group refused a message: sending privately")
    markup = await _markup(bot, mini_app, target, in_group=False)
    sent = False
    for admin_id in sorted(services.roles.admin_ids):
        sent = await _send(bot, admin_id, text, photo, markup, None) or sent
    return sent


async def _markup(
    bot: Bot, base: str | None, target: str | None, *, in_group: bool
) -> InlineKeyboardMarkup | None:
    if not target:
        return None
    button = await open_button(bot, base, target, in_group=in_group)
    return InlineKeyboardMarkup(inline_keyboard=[[button]]) if button else None


async def _send(
    bot: Bot,
    chat_id: int,
    text: str,
    photo,
    markup: InlineKeyboardMarkup | None,
    thread: int | None,
) -> bool:
    try:
        if photo is not None:
            try:
                await bot.send_photo(
                    chat_id,
                    photo,
                    caption=text[:1024],
                    reply_markup=markup,
                    message_thread_id=thread,
                )
                return True
            except Exception:  # noqa: BLE001 - the photo may be gone: text alone
                logger.info("Photo not sent to %s, sending text only", chat_id)
        await bot.send_message(
            chat_id,
            text,
            reply_markup=markup,
            message_thread_id=thread,
            disable_web_page_preview=True,
        )
        return True
    except Exception:  # noqa: BLE001 - the admin may not have opened the bot
        logger.warning("Message to %s not delivered", chat_id, exc_info=True)
        return False

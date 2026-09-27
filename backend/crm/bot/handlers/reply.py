import contextlib

from aiogram.enums import ChatType
from aiogram.types import Message

TELEGRAM_LIMIT = 4000  # a bit below the hard 4096 limit


def chunks(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split on line breaks so HTML tags (always within one line) stay intact."""
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


async def answer(message: Message, text: str) -> None:
    for part in chunks(text):
        await message.answer(part, disable_web_page_preview=True)


async def answer_privately(message: Message, text: str) -> None:
    """Answer an admin command sent in a group in the admin's private chat, so the
    bot writes nothing in the group; the command itself is removed if the bot may
    delete messages there. Falls back to the group if the admin never opened the bot."""
    if message.chat.type == ChatType.PRIVATE or message.from_user is None or message.bot is None:
        await answer(message, text)
        return
    try:
        for part in chunks(text):
            await message.bot.send_message(
                message.from_user.id, part, disable_web_page_preview=True
            )
    except Exception:  # noqa: BLE001 - no private chat with the bot yet
        await answer(message, text)
        return
    with contextlib.suppress(Exception):
        await message.delete()

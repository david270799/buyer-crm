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

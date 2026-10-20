"""«Витрина» in the bot (the owner, 20.10.2026): a shop link sent to the bot
privately by the admin becomes a draft card on «Подготовка»."""

import asyncio
import logging
from urllib.parse import urlencode, urlsplit, urlunsplit

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from crm.bot import formatting as fmt
from crm.bot.access import HasRole
from crm.config import Settings
from crm.domain.enums import Role
from crm.domain.errors import CRMError
from crm.domain.models import ShowcaseItem
from crm.services.common import Actor
from crm.services.container import Services
from crm.services.recognition import extract_urls

logger = logging.getLogger(__name__)
MAX_LINKS = 5


def draft_text(item: ShowcaseItem) -> str:
    lines = [f"🛍 <b>Черновик витрины</b> · {fmt.e(item.shop or '')}", fmt.e(item.title_line)]
    if item.shop_price_krw:
        lines.append(f"Цена в магазине: <b>₩ {item.shop_price_krw:,}</b>")
    sizes = [
        f"{s.get('name')}" + (f" ({s.get('stock')})" if s.get("stock") else "")
        for s in item.sizes
        if s.get("available")
    ]
    if sizes:
        lines.append("В наличии: " + fmt.e(", ".join(sizes)))
    if item.note:
        lines.append(f"⚠️ {fmt.e(item.note)}")
    lines.append("Проверьте цену и опубликуйте в «Одобрении».")
    return "\n".join(lines)


def build(services: Services, settings: Settings) -> Router:
    router = Router(name="showcase")

    def keyboard(item: ShowcaseItem) -> InlineKeyboardMarkup | None:
        if not settings.mini_app_url:
            return None
        parts = urlsplit(settings.mini_app_url)
        query = "&".join(q for q in (parts.query, urlencode({"open": f"prep:{item.id}"})) if q)
        url = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", query, ""))
        button = InlineKeyboardButton(text="Открыть в «Одобрении»", web_app=WebAppInfo(url=url))
        return InlineKeyboardMarkup(inline_keyboard=[[button]])

    async def on_link(message: Message, bot: Bot, actor: Actor | None) -> None:
        if actor is None or services.showcase is None:
            return
        for url in extract_urls(message.text)[:MAX_LINKS]:
            wait = await message.reply("Читаю страницу магазина…")
            where = {"chat_id": wait.chat.id, "message_id": wait.message_id}
            try:
                item = await asyncio.to_thread(services.showcase.add, actor, url)
            except CRMError as exc:
                await bot.edit_message_text(fmt.e(exc.user_message), **where)
                continue
            await bot.edit_message_text(draft_text(item), reply_markup=keyboard(item), **where)

    async def pagefile(message: Message, command: CommandObject, actor: Actor | None) -> None:
        """/pagefile <ссылка>: the page as this server sees it, as a file (to
        teach the CRM a new shop)."""
        if actor is None or services.showcase is None:
            return
        urls = extract_urls(command.args)
        if not urls:
            await message.answer("Пришлите так: <code>/pagefile https://ссылка-на-товар</code>")
            return
        try:
            html, final = await asyncio.to_thread(services.showcase.page_source, actor, urls[0])
        except CRMError as exc:
            await message.answer(f"❌ {fmt.e(exc.user_message)}")
            return
        name = (urlsplit(final).hostname or "page").replace(".", "_") + ".html"
        await message.answer_document(
            BufferedInputFile(html.encode("utf-8"), filename=name),
            caption=(
                "✅ Магазин пустил сервер. Перешлите этот файл в чат с разработчиком.\n"
                f"{fmt.e(final)}"
            ),
        )

    router.message.register(
        pagefile, Command("pagefile"), F.chat.type == ChatType.PRIVATE, HasRole(Role.ADMIN)
    )
    router.message.register(
        on_link,
        F.chat.type == ChatType.PRIVATE,
        F.text.contains("http"),
        ~F.text.startswith("/"),
        HasRole(Role.ADMIN),
    )
    return router

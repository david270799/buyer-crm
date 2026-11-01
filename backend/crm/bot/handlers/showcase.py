"""«Витрина» in the bot (the owner, 20.10.2026): a shop link sent to the bot
privately by the admin — or, since 01.11.2026, to the «Витрина» topic of the
admin group — becomes a draft card on «Подготовка»."""

import asyncio
import contextlib
import logging
from urllib.parse import urlsplit

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardMarkup,
    Message,
)

from crm.bot import formatting as fmt
from crm.bot.access import HasRole
from crm.bot.admin_group import in_topic, open_button
from crm.config import Settings
from crm.domain.enums import Role
from crm.domain.errors import CRMError
from crm.domain.models import ShowcaseItem
from crm.services.admin_group import SHOWCASE
from crm.services.common import Actor
from crm.services.container import Services
from crm.services.recognition import extract_urls

logger = logging.getLogger(__name__)
MAX_LINKS = 5


def draft_text(item: ShowcaseItem) -> str:
    lines = [f"🛍 <b>Черновик витрины</b> · {fmt.e(item.shop or '')}", fmt.e(item.title_line)]
    if item.code:
        lines.append(f"Код: <code>{fmt.e(item.code)}</code>")
    if item.from_screenshot and item.shop_price_krw:
        lines.append(f"Цена как на скриншоте: <b>₩ {item.shop_price_krw:,}</b>")
    elif item.shop_price_krw:
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
    if item.from_screenshot:
        lines.append("Впишите размеры и опубликуйте в «Одобрении».")
    else:
        lines.append("Проверьте цену и опубликуйте в «Одобрении».")
    return "\n".join(lines)


def build(services: Services, settings: Settings) -> Router:
    router = Router(name="showcase")

    async def keyboard(
        bot: Bot, item: ShowcaseItem, message: Message
    ) -> InlineKeyboardMarkup | None:
        button = await open_button(
            bot,
            settings.mini_app_url,
            f"prep:{item.id}",
            in_group=message.chat.type != ChatType.PRIVATE,
            text="Открыть в «Одобрении»",
        )
        return InlineKeyboardMarkup(inline_keyboard=[[button]]) if button else None

    def here(message: Message) -> bool:
        """Privately, or in the «Витрина» topic of the admin group (01.11.2026)."""
        return message.chat.type == ChatType.PRIVATE or in_topic(services, message, SHOWCASE)

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
            markup = await keyboard(bot, item, message)
            await bot.edit_message_text(draft_text(item), reply_markup=markup, **where)
            if item.shop_price_krw is None or not item.sizes:
                # A shop the CRM cannot read yet (the owner, 20.10.2026: no extra
                # command): the page itself, to teach the CRM this shop.
                await send_page(message, actor, url, unread=True)

    async def on_screenshot(message: Message, bot: Bot, actor: Actor | None) -> None:
        """A shop screenshot in the «Витрина» topic → a draft card (01.11.2026)."""
        if actor is None or services.showcase is None or not message.photo:
            return
        wait = await message.reply("Читаю скриншот и ищу фото модели…")
        where = {"chat_id": wait.chat.id, "message_id": wait.message_id}
        try:
            buffer = await bot.download(message.photo[-1].file_id)
            data = buffer.read() if buffer else b""
            item = await asyncio.to_thread(services.showcase.add_screenshot, actor, data)
        except CRMError as exc:
            await bot.edit_message_text(f"❌ {fmt.e(exc.user_message)}", **where)
            return
        markup = await keyboard(bot, item, message)
        text = draft_text(item)
        if item.photo_url and services.images is not None:
            # The card's first photo, so the result is visible without opening the CRM.
            picture = await asyncio.to_thread(services.images.read, item.photo_url)
            if picture:
                try:
                    await message.reply_photo(
                        BufferedInputFile(picture, f"{item.id}.jpg"),
                        caption=text[:1024],
                        reply_markup=markup,
                    )
                except Exception:  # noqa: BLE001 - the text below is enough
                    logger.info("Card photo not sent", exc_info=True)
                else:
                    with contextlib.suppress(Exception):
                        await bot.delete_message(**where)
                    return
        await bot.edit_message_text(text, reply_markup=markup, **where)

    async def send_page(message: Message, actor: Actor, url: str, *, unread: bool = False) -> None:
        """The shop page as this server gets it, as a file (to teach the CRM a shop)."""
        try:
            html, final = await asyncio.to_thread(services.showcase.page_source, actor, url)
        except CRMError as exc:
            await message.answer(f"❌ {fmt.e(exc.user_message)}")
            return
        name = (urlsplit(final).hostname or "page").replace(".", "_") + ".html"
        first = (
            "📄 Цену или размеры с этой страницы CRM пока прочитать не может."
            if unread
            else "✅ Магазин пустил сервер."
        )
        await message.answer_document(
            BufferedInputFile(html.encode("utf-8"), filename=name),
            caption=f"{first} Перешлите этот файл разработчику — он научит CRM этот магазин.",
        )

    async def pagefile(message: Message, command: CommandObject, actor: Actor | None) -> None:
        """/pagefile <ссылка>: the page as a file, on request."""
        if actor is None or services.showcase is None:
            return
        urls = extract_urls(command.args)
        if not urls:
            await message.answer("Пришлите так: <code>/pagefile https://ссылка-на-товар</code>")
            return
        await send_page(message, actor, urls[0])

    router.message.register(pagefile, Command("pagefile"), F.func(here), HasRole(Role.ADMIN))
    router.message.register(
        on_screenshot,
        F.photo,
        F.func(lambda m: in_topic(services, m, SHOWCASE)),
        HasRole(Role.ADMIN),
    )
    router.message.register(
        on_link,
        F.func(here),
        F.text.contains("http"),
        ~F.text.startswith("/"),
        HasRole(Role.ADMIN),
    )
    return router

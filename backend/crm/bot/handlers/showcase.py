"""«Витрина» in the bot (the owner, 20.10.2026): a shop link sent to the bot
privately by the admin — or, since 01.11.2026, to the «Витрина» topic of the
admin group — becomes a draft card on «Подготовка»."""

import asyncio
import contextlib
import logging
import random
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
from crm.services.showcase_service import ShopBlockedError, model_code

logger = logging.getLogger(__name__)
MAX_LINKS = 5
# SSG stops letting the bot in after about ten links in a row (the owner,
# 02.11.2026) and lets it in again a few minutes later: the bot waits and
# tries the same link again by itself.
RETRY_DELAYS = (60, 180, 420)
_retries: set[asyncio.Task] = set()
# Links are read one by one with a random pause between them (the owner,
# 02.11.2026: «25 секунд, 30 и т. д.»), so a shop does not take a burst of
# links for a robot. Includes the retries above.
LINK_GAP_SECONDS = (25.0, 40.0)
QUEUED = (
    "⏳ В очереди. Ссылки читаются по одной, с паузой 25–40 секунд, "
    "чтобы магазин не принял бота за робота."
)


class LinkQueue:
    """One link at a time, a random pause after each (one per dispatcher, so
    the lock lives on the bot's own event loop)."""

    def __init__(self) -> None:
        self._gate = asyncio.Lock()
        self._next_at = 0.0

    def busy(self) -> bool:
        return self._gate.locked()

    @contextlib.asynccontextmanager
    async def turn(self):
        async with self._gate:
            loop = asyncio.get_running_loop()
            delay = self._next_at - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                yield
            finally:
                low, high = LINK_GAP_SECONDS
                self._next_at = loop.time() + random.uniform(low, high)


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
    if item.from_screenshot and not item.shop_price_krw:
        # A card from an app's share link: the shop's site did not open.
        lines.append("Магазин не открылся: впишите цену и размеры в «Одобрении».")
    elif item.from_screenshot:
        lines.append("Впишите размеры и опубликуйте в «Одобрении».")
    else:
        lines.append("Проверьте цену и опубликуйте в «Одобрении».")
    return "\n".join(lines)


def build(services: Services, settings: Settings) -> Router:
    router = Router(name="showcase")
    queue = LinkQueue()

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
        waiting = []
        for url in extract_urls(message.text)[:MAX_LINKS]:
            busy = queue.busy() or bool(waiting)
            wait = await message.reply(QUEUED if busy else "Читаю страницу магазина…")
            waiting.append((url, {"chat_id": wait.chat.id, "message_id": wait.message_id}, busy))
        for url, where, busy in waiting:
            try:
                async with queue.turn():
                    if busy:
                        with contextlib.suppress(Exception):
                            await bot.edit_message_text("Читаю страницу магазина…", **where)
                    item = await asyncio.to_thread(services.showcase.add, actor, url)
            except ShopBlockedError:
                task = asyncio.create_task(retry_later(message, bot, actor, url, where))
                _retries.add(task)
                task.add_done_callback(_retries.discard)
                continue
            except CRMError as exc:
                await bot.edit_message_text(fmt.e(exc.user_message), **where)
                continue
            await show_draft(message, bot, actor, url, item, where)

    async def show_draft(
        message: Message, bot: Bot, actor: Actor, url: str, item: ShowcaseItem, where: dict
    ) -> None:
        markup = await keyboard(bot, item, message)
        await bot.edit_message_text(draft_text(item), reply_markup=markup, **where)
        if item.shop_price_krw is None or not item.sizes:
            # A shop the CRM cannot read yet (the owner, 20.10.2026: no extra
            # command): the page itself, to teach the CRM this shop.
            await send_page(message, actor, url, unread=True)

    async def retry_later(message: Message, bot: Bot, actor: Actor, url: str, where: dict) -> None:
        """The shop refused the bot: wait and try again, the same message
        telling how it goes; the link need not be sent again."""
        try:
            for attempt, delay in enumerate(RETRY_DELAYS, start=1):
                minutes = max(1, delay // 60)
                with contextlib.suppress(Exception):
                    await bot.edit_message_text(
                        "⏳ Магазин сейчас не пускает бота (защита от роботов). "
                        f"Попробую ещё раз через {minutes} мин. "
                        f"(попытка {attempt} из {len(RETRY_DELAYS)}), присылать заново не нужно.",
                        **where,
                    )
                await asyncio.sleep(delay)
                try:
                    async with queue.turn():
                        item = await asyncio.to_thread(services.showcase.add, actor, url)
                except ShopBlockedError:
                    continue
                except CRMError as exc:
                    await bot.edit_message_text(fmt.e(exc.user_message), **where)
                    return
                await show_draft(message, bot, actor, url, item, where)
                return
            await bot.edit_message_text(
                "❌ Магазин так и не пустил бота. Ссылка в порядке — пришлите её ещё раз позже.",
                **where,
            )
        except Exception:  # noqa: BLE001 - a background task: log, never crash the bot
            logger.exception("Showcase retry for %s failed", url)

    async def on_code(message: Message, bot: Bot, actor: Actor | None) -> None:
        """Model numbers alone in the «Витрина» topic («SYXS106», 02.11.2026):
        the brand's page (Swatch) or one found on the web → a draft card."""
        if actor is None or services.showcase is None:
            return
        codes = [c for c in (model_code(w) for w in (message.text or "").split()) if c]
        for code in list(dict.fromkeys(codes))[:MAX_LINKS]:
            wait = await message.reply(f"Ищу модель {fmt.e(code)}…")
            where = {"chat_id": wait.chat.id, "message_id": wait.message_id}
            try:
                item = await asyncio.to_thread(services.showcase.add_by_code, actor, code)
            except CRMError as exc:
                await bot.edit_message_text(f"❌ {fmt.e(exc.user_message)}", **where)
                continue
            markup = await keyboard(bot, item, message)
            await bot.edit_message_text(draft_text(item), reply_markup=markup, **where)

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
        on_code,
        F.text,
        ~F.text.startswith("/"),
        ~F.text.contains("http"),
        F.func(lambda m: in_topic(services, m, SHOWCASE)),
        F.func(lambda m: any(model_code(w) for w in (m.text or "").split())),
        HasRole(Role.ADMIN),
    )
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

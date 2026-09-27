"""Orders from photos: one message with a photo → one new order.

Who: the client in the orders group (or in a private chat with the bot); the
admin in a private chat (e.g. forwarding a client's photo). Photos the admin
posts in the group are not orders. Replies to other messages are treated as
conversation, not orders.

Steps: download → square WebP (services/image_service) → Gemini
(services/recognition) → store the photo → create the order
(services/intake_service) → reply to the photo with the order number.

Photos are processed in parallel (at most a few at a time), but orders from
one chat are numbered in the order the photos were sent.
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import JOIN_TRANSITION, ChatMemberUpdatedFilter, Command
from aiogram.types import ChatMemberUpdated, Message

from crm.bot import formatting as fmt
from crm.bot.access import audience_for
from crm.config import Settings
from crm.domain.enums import Role
from crm.domain.errors import CRMError
from crm.services.common import Actor
from crm.services.container import Services
from crm.services.image_service import ORDER_PHOTOS_FOLDER, StoredImage, process_image
from crm.services.intake_service import IncomingOrder
from crm.services.recognition import Recognition, recognize_safely

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 20 * 1024 * 1024  # Bot API download limit
# Telegram's stand-in sender for group admins with "Remain anonymous" on.
ANONYMOUS_ADMIN_ID = 1087968824
PARALLEL = 3


@dataclass
class _Prepared:
    main: bytes
    thumb: bytes
    size: tuple[int, int]
    recognition: Recognition


def _file_id(message: Message) -> str | None:
    if message.photo:
        return message.photo[-1].file_id  # the largest size
    document = message.document
    if document and (document.mime_type or "").startswith("image/"):
        if document.file_size and document.file_size > MAX_FILE_BYTES:
            return None
        return document.file_id
    return None


def is_order_photo(message: Message, role: Role | None) -> bool:
    if _file_id(message) is None or message.reply_to_message is not None:
        return False
    if role is Role.CLIENT:
        return True
    return role is Role.ADMIN and message.chat.type == ChatType.PRIVATE


def message_link(chat_id: int, message_id: int) -> str | None:
    """t.me link to a message in a supergroup (private groups included)."""
    text = str(chat_id)
    return f"https://t.me/c/{text[4:]}/{message_id}" if text.startswith("-100") else None


class PhotoIntake:
    def __init__(self, services: Services, settings: Settings):
        self._services = services
        self._settings = settings
        self._slots = asyncio.Semaphore(PARALLEL)
        self._last: dict[int, asyncio.Future] = {}

    async def _prepare(self, bot: Bot, message: Message) -> _Prepared:
        file_id = _file_id(message)
        assert file_id is not None
        buffer = await bot.download(file_id)
        data = buffer.read() if buffer else b""
        main, thumb, size = await asyncio.to_thread(process_image, data)
        caption = message.caption or message.text
        recognition = await asyncio.to_thread(
            recognize_safely, self._services.recognizer, main, caption
        )
        return _Prepared(main, thumb, size, recognition)

    async def _store(self, prepared: _Prepared) -> StoredImage | None:
        if self._services.images is None:
            return None
        try:
            return await asyncio.to_thread(
                self._services.images.store_processed,
                prepared.main,
                prepared.thumb,
                prepared.size,
                folder=ORDER_PHOTOS_FOLDER,
            )
        except Exception:  # noqa: BLE001 - the order matters more than the picture
            logger.exception("Could not store an order photo")
            return None

    async def handle(
        self, bot: Bot, message: Message, actor: Actor, *, force: bool = False
    ) -> None:
        """`message` is the photo; `force` accepts it even if it does not look like an order."""
        chat_id = message.chat.id
        if await asyncio.to_thread(self._services.intake.existing, chat_id, message.message_id):
            return  # a redelivered update
        loop = asyncio.get_running_loop()
        previous, mine = self._last.get(chat_id), loop.create_future()
        self._last[chat_id] = mine
        try:
            async with self._slots:
                with contextlib.suppress(Exception):
                    await bot.send_chat_action(chat_id, "typing")
                prepared = await self._prepare(bot, message)
            if previous is not None:
                await asyncio.shield(previous)  # keep the numbering in sending order
            if prepared.recognition.not_a_product and not force:
                await self._not_an_order(bot, message)
                return
            photo = await self._store(prepared)
            result = await asyncio.to_thread(
                self._services.intake.accept,
                actor,
                IncomingOrder(
                    chat_id=chat_id,
                    message_id=message.message_id,
                    caption=message.caption or message.text,
                    photo=photo,
                    recognition=prepared.recognition,
                ),
            )
            if not result.already_done:
                audience = audience_for(actor.role, message.chat)
                await message.reply(fmt.intake_accepted(result.order, audience))
        except CRMError as exc:
            await message.reply(f"⚠️ {fmt.e(exc.user_message)}")
        except Exception:  # noqa: BLE001 - network, storage: the client can resend
            logger.exception("Could not accept photo %s/%s", chat_id, message.message_id)
            with contextlib.suppress(Exception):
                await message.reply(fmt.INTAKE_FAILED)
        finally:
            mine.set_result(None)
            if self._last.get(chat_id) is mine:
                del self._last[chat_id]

    async def _not_an_order(self, bot: Bot, message: Message) -> None:
        logger.info("Photo %s/%s does not look like an order", message.chat.id, message.message_id)
        text = fmt.intake_not_an_order(message_link(message.chat.id, message.message_id))
        if message.chat.type == ChatType.PRIVATE:
            await message.reply(text)
            return
        for admin_id in sorted(self._settings.admin_ids):
            with contextlib.suppress(Exception):
                await bot.send_message(admin_id, text)


def build(services: Services, settings: Settings) -> Router:
    router = Router(name="intake")
    intake = PhotoIntake(services, settings)

    async def on_photo(message: Message, bot: Bot, actor: Actor | None, role: Role | None) -> None:
        if actor is None or not is_order_photo(message, role):
            return
        await intake.handle(bot, message, actor)

    async def on_add(message: Message, bot: Bot, actor: Actor | None, role: Role | None) -> None:
        """/add in reply to a photo: accept it as an order even if it did not look like one."""
        target = message.reply_to_message
        if role is not Role.ADMIN or actor is None:
            return
        if target is None or _file_id(target) is None:
            await message.reply("Ответьте командой /add на сообщение с фото товара.")
            return
        existing = await asyncio.to_thread(
            services.intake.existing, target.chat.id, target.message_id
        )
        if existing:
            await message.reply(f"Этот заказ уже принят: {fmt.e(existing)}")
            return
        await intake.handle(bot, target, actor, force=True)

    async def on_added_to_group(event: ChatMemberUpdated, bot: Bot) -> None:
        adder = event.from_user
        chat = event.chat
        if adder is None or adder.id not in settings.admin_ids:
            logger.warning("Added to chat %s by non-admin %s: leaving", chat.id, adder and adder.id)
            with contextlib.suppress(Exception):
                await bot.leave_chat(chat.id)
            anonymous = adder is not None and adder.id == ANONYMOUS_ADMIN_ID
            text = fmt.group_left_for_admin(chat.title or "группа", anonymous)
            for admin_id in sorted(settings.admin_ids):
                with contextlib.suppress(Exception):
                    await bot.send_message(admin_id, text)
            return
        me = await bot.get_me()
        is_admin = event.new_chat_member.status == ChatMemberStatus.ADMINISTRATOR
        sees_photos = bool(me.can_read_all_group_messages) or is_admin
        with contextlib.suppress(Exception):
            await bot.send_message(chat.id, fmt.GROUP_WELCOME)
        text = fmt.group_added_for_admin(chat.title or "группа", chat.id, sees_photos)
        for admin_id in sorted(settings.admin_ids):
            with contextlib.suppress(Exception):
                await bot.send_message(admin_id, text)

    router.message.register(on_add, Command("add"))
    router.message.register(on_photo, F.photo | F.document)
    router.my_chat_member.register(on_added_to_group, ChatMemberUpdatedFilter(JOIN_TRANSITION))
    return router

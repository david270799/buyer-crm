"""Photo → order through the real aiogram Dispatcher, with a fake Telegram and Gemini."""

import asyncio
import io
import threading
import time
from datetime import datetime, timezone
from itertools import count

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import GetFile, GetMe, LeaveChat, SendMessage
from aiogram.types import (
    Chat,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberUpdated,
    File,
    Message,
    PhotoSize,
    Update,
    User,
)
from conftest import ADMIN_TG, CLIENT_TG, START_BALANCE, balance, seed_order
from PIL import Image

from crm.bot.app import create_dispatcher
from crm.config import Settings
from crm.services.container import build_services
from crm.services.recognition import Recognition, fallback
from crm.storage.blobs import MemoryBlobStorage

pytestmark = pytest.mark.usefixtures("client_doc")

GROUP = -1001234567890
BOT_USER = User(id=42, is_bot=True, first_name="CRM", username="crm_bot")
_ids = count(1000)


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (30, 120, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


class FakeTelegram(BaseSession):
    def __init__(self, *, reads_groups=True, broken_download=False):
        super().__init__()
        self.sent: list = []
        self.reads_groups = reads_groups
        self.broken_download = broken_download

    async def make_request(self, bot, method, timeout=None):
        self.sent.append(method)
        if isinstance(method, GetMe):
            return BOT_USER.model_copy(update={"can_read_all_group_messages": self.reads_groups})
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u", file_path="photos/p.jpg")
        if isinstance(method, SendMessage):
            return Message(
                message_id=next(_ids),
                date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        return True

    async def stream_content(
        self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True
    ):
        if self.broken_download:
            raise ConnectionError("download failed")
        yield _jpeg()

    async def close(self):
        pass

    def messages(self, chat_id=None) -> list[SendMessage]:
        return [
            m
            for m in self.sent
            if isinstance(m, SendMessage) and (chat_id is None or m.chat_id == chat_id)
        ]


class FakeGemini:
    engine = "gemini-fake"

    def __init__(self, *, not_a_product=False, slow_first=0.0):
        self.not_a_product = not_a_product
        self.slow_first = slow_first
        self.calls: list[str | None] = []
        self._lock = threading.Lock()

    def recognize(self, image: bytes, text: str | None) -> Recognition:
        with self._lock:
            self.calls.append(text)
            first = len(self.calls) == 1
        if first and self.slow_first:
            time.sleep(self.slow_first)
        assert image[:4] == b"RIFF"  # the standardised WebP, not the original
        if self.not_a_product:
            return Recognition(not_a_product=True, confidence=0.95, engine=self.engine)
        base = fallback(text)
        return Recognition(
            brand="Nike",
            model=f"Dunk {text or ''}".strip(),
            size=base.size,
            link=base.link,
            confidence=0.9,
            engine=self.engine,
        )


def _settings() -> Settings:
    return Settings(
        bot_token="42:TEST",
        admin_ids=frozenset({ADMIN_TG}),
        allowed_chat_ids=frozenset(),
        firebase_project_id=None,
        firebase_credentials_path=None,
        firebase_credentials_json=None,
        firebase_storage_bucket=None,
        gemini_api_key=None,
        log_level="INFO",
    )


@pytest.fixture
def env(db, clock):
    def make(gemini=None, **session_kwargs):
        blobs = MemoryBlobStorage()
        services = build_services(
            db, frozenset({ADMIN_TG}), clock, blob_storage=blobs, recognizer=gemini
        )
        session = FakeTelegram(**session_kwargs)
        bot = Bot(
            "42:TEST", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        dp = create_dispatcher(services, _settings())

        async def photo(
            caption=None, user_id=CLIENT_TG, chat_id=GROUP, message_id=None, reply_to=None
        ):
            chat_type = "private" if chat_id > 0 else "supergroup"
            message = Message(
                message_id=message_id or next(_ids),
                date=datetime.now(timezone.utc),
                chat=Chat(id=chat_id, type=chat_type),
                from_user=User(id=user_id, is_bot=False, first_name="U"),
                photo=[
                    PhotoSize(file_id="small", file_unique_id="s", width=90, height=90),
                    PhotoSize(file_id="big", file_unique_id="b", width=1280, height=960),
                ],
                caption=caption,
                reply_to_message=reply_to,
            )
            await dp.feed_update(bot, Update(update_id=next(_ids), message=message))
            return message

        async def text(value, user_id=ADMIN_TG, chat_id=GROUP, reply_to=None):
            chat_type = "private" if chat_id > 0 else "supergroup"
            message = Message(
                message_id=next(_ids),
                date=datetime.now(timezone.utc),
                chat=Chat(id=chat_id, type=chat_type),
                from_user=User(id=user_id, is_bot=False, first_name="U"),
                text=value,
                reply_to_message=reply_to,
            )
            await dp.feed_update(bot, Update(update_id=next(_ids), message=message))

        async def added_by(user_id):
            event = ChatMemberUpdated(
                chat=Chat(id=GROUP, type="supergroup", title="Заказы"),
                from_user=User(id=user_id, is_bot=False, first_name="U"),
                date=datetime.now(timezone.utc),
                old_chat_member=ChatMemberLeft(user=BOT_USER),
                new_chat_member=ChatMemberMember(user=BOT_USER),
            )
            await dp.feed_update(bot, Update(update_id=next(_ids), my_chat_member=event))

        return {
            "services": services,
            "session": session,
            "blobs": blobs,
            "photo": photo,
            "text": text,
            "added_by": added_by,
        }

    return make


async def test_client_photo_in_group_becomes_an_order(db, env):
    seed_order(db, "n125")
    gemini = FakeGemini()
    e = env(gemini)

    await e["photo"]("42 https://shop.example.kr/item/7")

    order = db.get("orders", "n126")
    assert order["status"] == "new" and order["brand"] == "Nike" and order["size"] == "42"
    assert order["source_url"] == "https://shop.example.kr/item/7"
    assert order["photo_url"].endswith(".webp") and len(e["blobs"].files) == 2
    assert order["recognition"]["engine"] == "gemini-fake"
    [reply] = e["session"].messages(GROUP)
    assert "Заказ n126 принят" in reply.text and "Размер: 42" in reply.text
    assert "shop.example.kr" not in reply.text and "Gemini" not in reply.text  # client sees it
    assert reply.reply_parameters or reply.reply_to_message_id  # answers that very photo
    assert balance(db) == START_BALANCE


async def test_redelivered_photo_is_accepted_once(db, env):
    e = env(FakeGemini())
    first = await e["photo"]("42")
    await e["photo"]("42", message_id=first.message_id)

    assert len(db.list_ids("orders")) == 1
    assert len(e["session"].messages(GROUP)) == 1


async def test_who_can_order(db, env):
    e = env(FakeGemini())
    await e["photo"]("42", user_id=ADMIN_TG)  # the admin posting in the group: not an order
    await e["photo"]("42", user_id=555)  # a stranger
    await e["photo"](
        "42",
        reply_to=Message(
            message_id=1,
            date=datetime.now(timezone.utc),
            chat=Chat(id=GROUP, type="supergroup"),
            text="где мой заказ?",
        ),
    )  # a reply is conversation
    assert db.list_ids("orders") == []

    await e["photo"]("43 https://shop.example.kr/x", user_id=ADMIN_TG, chat_id=ADMIN_TG)
    [order_id] = db.list_ids("orders")
    [reply] = e["session"].messages(ADMIN_TG)
    assert f"Заказ {order_id} принят" in reply.text
    assert "🔒 Ссылка" in reply.text and "Gemini" in reply.text and "/buy" in reply.text


async def test_not_an_order_goes_to_the_admin_and_add_forces_it(db, env):
    e = env(FakeGemini(not_a_product=True))
    photo = await e["photo"]("вот коробка пришла")

    assert db.list_ids("orders") == []
    assert e["session"].messages(GROUP) == []
    [note] = e["session"].messages(ADMIN_TG)
    assert "/add" in note.text and "t.me/c/1234567890/" in note.text

    await e["text"]("/add", reply_to=photo)
    assert len(db.list_ids("orders")) == 1
    assert db.get("orders", db.list_ids("orders")[0])["created_by"] == f"tg:{ADMIN_TG}"
    await e["text"]("/add", reply_to=photo)
    assert len(db.list_ids("orders")) == 1
    assert "уже принят" in e["session"].messages(GROUP)[-1].text


async def test_photos_sent_together_keep_their_order(db, env):
    seed_order(db, "n125")
    e = env(FakeGemini(slow_first=0.3))  # the first photo is recognised last

    first, second, third = (next(_ids) for _ in range(3))
    await asyncio.gather(
        e["photo"]("первая 41", message_id=first),
        e["photo"]("вторая 42", message_id=second),
        e["photo"]("третья 43", message_id=third),
    )

    new_ids = [i for i in db.list_ids("orders") if i != "n125"]
    by_message = {db.get("orders", i)["source_message_id"]: i for i in new_ids}
    assert [by_message[m] for m in (first, second, third)] == ["n126", "n127", "n128"]


async def test_without_gemini_the_caption_is_used(db, env):
    e = env(None)
    await e["photo"]("270 https://shop.example.kr/p")

    [order_id] = db.list_ids("orders")
    order = db.get("orders", order_id)
    assert order["size"] == "270" and order["brand"] is None
    assert order["source_url"] == "https://shop.example.kr/p"
    assert "Модель уточнит администратор" in e["session"].messages(GROUP)[0].text


async def test_download_problem_asks_to_resend(db, env):
    e = env(FakeGemini(), broken_download=True)
    await e["photo"]("42")
    assert db.list_ids("orders") == []
    assert "ещё раз" in e["session"].messages(GROUP)[0].text


async def test_added_to_group_by_admin_greets_and_reports_the_id(db, env):
    e = env(FakeGemini(), reads_groups=False)
    await e["added_by"](ADMIN_TG)

    [welcome] = e["session"].messages(GROUP)
    assert "принимаю заказы" in welcome.text
    [note] = e["session"].messages(ADMIN_TG)
    assert str(GROUP) in note.text and "/setprivacy" in note.text
    assert not any(isinstance(m, LeaveChat) for m in e["session"].sent)


async def test_added_to_group_by_a_stranger_leaves(db, env):
    e = env(FakeGemini())
    await e["added_by"](555)
    assert any(isinstance(m, LeaveChat) for m in e["session"].sent)
    assert e["session"].messages(GROUP) == []

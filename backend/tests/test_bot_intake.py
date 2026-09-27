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
from aiogram.methods import DeleteMessage, GetFile, GetMe, LeaveChat, SendMessage, SendPhoto
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
        if isinstance(method, (SendMessage, SendPhoto)):
            return Message(
                message_id=next(_ids),
                date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="private"),
                text=getattr(method, "text", None) or getattr(method, "caption", None),
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

    def to(self, chat_id) -> list[str]:
        """Texts and photo captions the bot sent to a chat."""
        return [
            m.text if isinstance(m, SendMessage) else (m.caption or "")
            for m in self.sent
            if isinstance(m, (SendMessage, SendPhoto)) and m.chat_id == chat_id
        ]

    def photos_to(self, chat_id) -> list[SendPhoto]:
        return [m for m in self.sent if isinstance(m, SendPhoto) and m.chat_id == chat_id]

    def deleted(self) -> list[int]:
        return [m.message_id for m in self.sent if isinstance(m, DeleteMessage)]

    def messages(self, chat_id=None) -> list[SendMessage]:
        return [
            m
            for m in self.sent
            if isinstance(m, SendMessage) and (chat_id is None or m.chat_id == chat_id)
        ]


class FakeGemini:
    engine = "gemini-fake"

    def __init__(self, *, not_a_product=False, slow_first=0.0, unsure=False):
        self.not_a_product = not_a_product
        self.unsure = unsure
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
        if self.unsure:
            return Recognition(size=base.size, link=base.link, confidence=0.3, engine=self.engine)
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


async def test_photo_in_group_becomes_an_order_silently(db, env):
    seed_order(db, "n125")
    e = env(FakeGemini())

    await e["photo"]("42 https://shop.example.kr/item/7")

    order = db.get("orders", "n126")
    assert order["status"] == "new" and order["brand"] == "Nike" and order["size"] == "42"
    assert order["source_url"] == "https://shop.example.kr/item/7"
    assert order["photo_url"].endswith(".webp") and len(e["blobs"].files) == 2
    assert order["recognition"]["engine"] == "gemini-fake"
    assert e["session"].to(GROUP) == []  # the bot writes nothing in the group
    assert e["session"].to(ADMIN_TG) == []  # nothing to ask either
    assert balance(db) == START_BALANCE


async def test_redelivered_photo_is_accepted_once(db, env):
    e = env(FakeGemini())
    first = await e["photo"]("42")
    await e["photo"]("42", message_id=first.message_id)

    assert len(db.list_ids("orders")) == 1


async def test_assistants_in_the_group_can_order(db, env):
    e = env(FakeGemini())
    await e["photo"]("42", user_id=555)  # the client's assistant

    [order_id] = db.list_ids("orders")
    assert db.get("orders", order_id)["created_by"] == "tg:555"
    assert e["session"].to(GROUP) == []


async def test_what_is_not_an_order(db, env):
    e = env(FakeGemini())
    await e["photo"]("42", user_id=ADMIN_TG)  # the admin's own photo in the group
    await e["photo"]("42", user_id=555, chat_id=555)  # a stranger in a private chat
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
    assert e["session"].to(GROUP) == []


async def test_admin_in_private_gets_the_order_card(db, env):
    e = env(FakeGemini())
    await e["photo"]("43 https://shop.example.kr/x", user_id=ADMIN_TG, chat_id=ADMIN_TG)

    [order_id] = db.list_ids("orders")
    [reply] = e["session"].to(ADMIN_TG)
    assert f"Заказ {order_id} принят" in reply
    assert "🔒 Ссылка" in reply and "Gemini" in reply and "/buy" in reply


async def test_questions_go_to_the_admin_with_the_photo(db, env):
    e = env(FakeGemini(unsure=True))
    await e["photo"]("вот эти, срочно", user_id=555)

    [order_id] = db.list_ids("orders")
    assert e["session"].to(GROUP) == []
    [question] = e["session"].photos_to(ADMIN_TG)
    assert question.photo == "big"  # the client's own photo, resent by file_id
    assert f"Заказ {order_id}" in question.caption
    assert "модель не распознана" in question.caption and "размер не указан" in question.caption
    assert "t.me/c/1234567890/" in question.caption and "срочно" in question.caption


async def test_not_an_order_goes_to_the_admin_and_add_forces_it(db, env):
    e = env(FakeGemini(not_a_product=True))
    photo = await e["photo"]("вот коробка пришла")

    assert db.list_ids("orders") == []
    [note] = e["session"].to(ADMIN_TG)
    assert "/add" in note and "t.me/c/1234567890/" in note

    await e["text"]("/add", reply_to=photo)
    [order_id] = db.list_ids("orders")
    assert db.get("orders", order_id)["created_by"] == f"tg:{ADMIN_TG}"
    assert f"Заказ {order_id} принят" in e["session"].to(ADMIN_TG)[-1]
    await e["text"]("/add", reply_to=photo)
    assert len(db.list_ids("orders")) == 1
    assert "уже принят" in e["session"].to(ADMIN_TG)[-1]
    assert e["session"].to(GROUP) == []
    assert len(e["session"].deleted()) == 2  # the /add commands are removed from the group


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
    assert e["session"].to(GROUP) == []
    [question] = e["session"].to(ADMIN_TG)
    assert "модель не распознана (GEMINI_API_KEY не задан)" in question


async def test_download_problem_is_reported_to_the_admin(db, env):
    e = env(FakeGemini(), broken_download=True)
    await e["photo"]("42")
    assert db.list_ids("orders") == []
    assert e["session"].to(GROUP) == []
    assert "не принято" in e["session"].to(ADMIN_TG)[0]


async def test_added_to_group_by_admin_stays_silent_and_reports_the_id(db, env):
    e = env(FakeGemini(), reads_groups=False)
    await e["added_by"](ADMIN_TG)

    assert e["session"].to(GROUP) == []
    [note] = e["session"].to(ADMIN_TG)
    assert str(GROUP) in note and "/setprivacy" in note and "ничего не пишу" in note
    assert not any(isinstance(m, LeaveChat) for m in e["session"].sent)


async def test_added_to_group_by_a_stranger_leaves(db, env):
    e = env(FakeGemini())
    await e["added_by"](555)
    assert any(isinstance(m, LeaveChat) for m in e["session"].sent)
    assert e["session"].messages(GROUP) == []
    assert "не администратор" in e["session"].messages(ADMIN_TG)[0].text


async def test_added_by_an_anonymous_admin_explains_how_to_fix(db, env):
    e = env(FakeGemini())
    await e["added_by"](1087968824)
    assert any(isinstance(m, LeaveChat) for m in e["session"].sent)
    assert "Анонимность" in e["session"].messages(ADMIN_TG)[0].text


async def test_setclient_by_reply_keeps_the_balance(db, env):
    e = env(FakeGemini())
    client_message = Message(
        message_id=7,
        date=datetime.now(timezone.utc),
        chat=Chat(id=GROUP, type="supergroup"),
        from_user=User(id=3003, is_bot=False, first_name="Ким", last_name="Мин"),
        text="привет",
    )
    await e["text"]("/setclient", reply_to=client_message)

    client = db.get("client_info", "main_client")
    assert client["telegram_id"] == 3003 and client["name"] == "Ким Мин"
    assert client["balance"] == START_BALANCE  # never touched
    assert e["services"].roles.resolve(3003).value == "client"  # recognised at once
    assert e["services"].roles.resolve(CLIENT_TG) is None
    assert e["session"].to(GROUP) == []  # answered privately
    assert "Раньше был" in e["session"].to(ADMIN_TG)[-1]
    assert e["session"].deleted()  # the command itself is removed from the group


async def test_setclient_rules(db, env):
    e = env(FakeGemini())
    await e["text"](f"/setclient {ADMIN_TG}")
    assert "администратора" in e["session"].to(ADMIN_TG)[-1]
    await e["text"]("/setclient 3003", user_id=CLIENT_TG)  # the client cannot
    await e["text"]("/setclient abc")
    assert "Ответьте командой /setclient" in e["session"].to(ADMIN_TG)[-1]
    assert db.get("client_info", "main_client")["telegram_id"] == CLIENT_TG
    assert e["session"].to(GROUP) == []


async def test_assistants_get_no_client_access(db, env):
    e = env(FakeGemini())
    for command in ("/balance", "/history", "/order 1", "/shipments"):
        await e["text"](command, user_id=555)
    await e["text"]("/start", user_id=555, chat_id=555)

    assert e["session"].to(GROUP) == []
    assert "закрытая" in e["session"].to(555)[0]  # no menu, no CRM button
    assert e["services"].roles.resolve(555) is None  # the Mini App says "нет доступа"


def test_setclient_creates_a_missing_client_with_zero_balance(db, services, admin):
    from crm.storage.memory import InMemoryDatabase

    # The client_doc fixture seeded one; remove it (there is no delete in the storage port).
    if isinstance(db, InMemoryDatabase):
        db._docs["client_info"].clear()
    else:
        db.client.collection("client_info").document("main_client").delete()

    change = services.clients.set_client(admin, 3003, "Ким")

    assert change.before is None
    stored = db.get("client_info", "main_client")
    assert stored["telegram_id"] == 3003 and stored["balance"] == 0

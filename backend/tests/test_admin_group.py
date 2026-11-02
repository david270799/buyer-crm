"""The admin's group with topics (the owner, 01.11.2026): /topic, «Склад»,
«Витрина» links and «Уведомления», through the real aiogram Dispatcher."""

from datetime import datetime, timezone
from itertools import count

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.methods import SendMessage, SendPhoto
from aiogram.types import Chat, ForumTopicCreated, Message, PhotoSize, Update, User
from conftest import ADMIN_TG, CLIENT_TG, seed_order
from test_bot_intake import FakeTelegram, _settings

from crm.bot.app import create_dispatcher
from crm.bot.notifier import TelegramNotifier
from crm.domain.enums import Role
from crm.domain.errors import PermissionDeniedError
from crm.services.admin_group import NOTIFICATIONS, SHOWCASE, WAREHOUSE, kind_from_text
from crm.services.common import Actor
from crm.services.container import build_services
from crm.storage.blobs import MemoryBlobStorage

pytestmark = pytest.mark.usefixtures("client_doc")

ADMIN_CHAT = -1009876543210
ORDERS_CHANNEL = -1001234567890
TOPICS = {"🏠 Склад": 11, "🛍 Ветрина": 12, "📣 Уведомления": 13, "General": None}
_ids = count(5000)


def test_topic_kinds_from_names():
    assert kind_from_text("🏠 Склад") == WAREHOUSE
    assert kind_from_text("Ветрина") == SHOWCASE  # the owner's spelling
    assert kind_from_text("витрина") == SHOWCASE
    assert kind_from_text("📣 Уведомления") == NOTIFICATIONS
    assert kind_from_text("General") is None


def test_binding_keeps_one_group_and_one_job_per_topic(db, clock):
    services = build_services(db, frozenset({ADMIN_TG}), clock)
    admin = Actor.telegram(ADMIN_TG, Role.ADMIN)
    group = services.admin_group
    group.bind(admin, ADMIN_CHAT, "Korea Buyer", 11, WAREHOUSE)
    group.bind(admin, ADMIN_CHAT, "Korea Buyer", 12, SHOWCASE)
    now = group.bind(admin, ADMIN_CHAT, "Korea Buyer", 11, NOTIFICATIONS)  # topic 11 changes job
    assert now.topics == {SHOWCASE: 12, NOTIFICATIONS: 11}
    assert now.kind_of(ADMIN_CHAT, 12) == SHOWCASE and now.kind_of(-1, 12) is None
    other = group.bind(admin, -100555, "Другая", 7, WAREHOUSE)  # another group: start over
    assert other.chat_id == -100555 and other.topics == {WAREHOUSE: 7}
    with pytest.raises(PermissionDeniedError):
        group.bind(Actor.telegram(CLIENT_TG, Role.CLIENT), ADMIN_CHAT, None, 11, WAREHOUSE)
    assert group.unbind(admin).chat_id is None


@pytest.fixture
def env(db, clock):
    services = build_services(
        db, frozenset({ADMIN_TG}), clock, blob_storage=MemoryBlobStorage(), recognizer=None
    )
    session = FakeTelegram()
    bot = Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # A non-empty allow-list: the admin group must still work without /setgroup.
    settings = _settings()
    object.__setattr__(settings, "allowed_chat_ids", frozenset({ORDERS_CHANNEL}))
    object.__setattr__(settings, "mini_app_url", "https://crm.example/")
    dp = create_dispatcher(services, settings)

    def topic_message(topic: str, user_id: int, **fields) -> Message:
        thread = TOPICS[topic]
        chat = Chat(id=ADMIN_CHAT, type="supergroup", title="Korea Buyer", is_forum=True)
        head = None
        if thread is not None:
            head = Message(
                message_id=thread,
                date=datetime.now(timezone.utc),
                chat=chat,
                forum_topic_created=ForumTopicCreated(name=topic, icon_color=0),
            )
        return Message(
            message_id=next(_ids),
            date=datetime.now(timezone.utc),
            chat=chat,
            from_user=User(id=user_id, is_bot=False, first_name="U"),
            message_thread_id=thread,
            is_topic_message=thread is not None or None,
            reply_to_message=head,
            **fields,
        )

    async def say(topic: str, text: str, user_id: int = ADMIN_TG) -> None:
        message = topic_message(topic, user_id, text=text)
        await dp.feed_update(bot, Update(update_id=next(_ids), message=message))

    async def photo(topic: str, caption: str | None = None, user_id: int = ADMIN_TG) -> None:
        message = topic_message(
            topic,
            user_id,
            caption=caption,
            photo=[PhotoSize(file_id="big", file_unique_id="b", width=1280, height=960)],
        )
        await dp.feed_update(bot, Update(update_id=next(_ids), message=message))

    async def bind_all() -> None:
        for name in ("🏠 Склад", "🛍 Ветрина", "📣 Уведомления"):
            await say(name, "/topic")

    class Env:
        pass

    e = Env()
    e.services, e.session, e.bot, e.say, e.photo, e.bind_all = (
        services,
        session,
        bot,
        say,
        photo,
        bind_all,
    )
    return e


def in_thread(session: FakeTelegram, thread: int | None) -> list[str]:
    return [
        (m.text if isinstance(m, SendMessage) else m.caption) or ""
        for m in session.sent
        if isinstance(m, (SendMessage, SendPhoto))
        and m.chat_id == ADMIN_CHAT
        and m.message_thread_id == thread
    ]


async def test_topic_command_binds_by_the_topic_name(env):
    await env.say("🛍 Ветрина", "/topic")
    group = env.services.admin_group.current()
    assert group.chat_id == ADMIN_CHAT and group.topic(SHOWCASE) == 12
    answer = in_thread(env.session, 12)[-1]
    assert "«Витрина»" in answer and "Осталось привязать" in answer
    await env.say("General", "/topic")  # not inside a topic: only the usage
    assert "внутри темы" in in_thread(env.session, None)[-1]
    await env.say("🏠 Склад", "/topic", user_id=CLIENT_TG)  # not an admin: ignored
    assert env.services.admin_group.current().topic(WAREHOUSE) is None
    await env.say("🏠 Склад", "/topic склад")
    await env.say("📣 Уведомления", "/topic")
    assert "Все три темы привязаны" in in_thread(env.session, 13)[-1]


async def test_warehouse_photo_asks_which_bought_order(env, db):
    seed_order(db, "N3", status="bought", brand="Nike", model="Dunk", size="270")
    await env.bind_all()
    await env.photo("🏠 Склад")
    question = [
        m
        for m in env.session.sent
        if isinstance(m, SendMessage) and m.message_thread_id == 11 and "Какой это заказ" in m.text
    ]
    assert question, in_thread(env.session, 11)
    buttons = [b.text for row in question[-1].reply_markup.inline_keyboard for b in row]
    assert any(b.startswith("N3") for b in buttons)
    assert not any("новый заказ" in b for b in buttons)  # only arrivals in «Склад»
    # A photo in another topic is not an arrival and not an order.
    before = len(env.session.sent)
    await env.photo("📣 Уведомления")
    assert len(env.session.sent) == before
    assert db.get("orders", "N4") is None


async def test_admin_notices_go_to_the_notifications_topic(env):
    from crm.bot.admin_group import tell_admins

    await tell_admins(env.bot, env.services, "До привязки — в личку")
    assert "До привязки — в личку" in env.session.to(ADMIN_TG)
    await env.bind_all()
    await tell_admins(
        env.bot,
        env.services,
        "Вопрос по заказу",
        mini_app="https://crm.example/",
        target="order:N5",
    )
    sent = [m for m in env.session.messages() if m.text == "Вопрос по заказу"]
    assert len(sent) == 1 and sent[0].chat_id == ADMIN_CHAT and sent[0].message_thread_id == 13
    button = sent[0].reply_markup.inline_keyboard[0][0]
    assert button.url == "https://t.me/crm_bot?startapp=order-N5" and button.web_app is None


async def test_notifier_sends_the_admins_copy_once_to_the_topic(env, db, clock):
    from crm.domain.notifications import NotifyRecipient

    await env.bind_all()
    admin = Actor.telegram(ADMIN_TG, Role.ADMIN)
    env.services.notifications.update_settings(admin, recipient=NotifyRecipient.BOTH, level="all")
    seed_order(db, "N7", status="new", brand="Nike", model="Dunk", size="270")
    env.services.orders.buy(admin, "N7", 100000, 120000)
    notifier = TelegramNotifier(
        env.bot,
        env.services.notifications,
        "https://crm.example/",
        pause_seconds=0,
        admin_ids=frozenset({ADMIN_TG}),
        admin_group=env.services.admin_group.current,
    )
    assert await notifier.run_once() >= 1
    group_texts = in_thread(env.session, 13)
    assert any("N7" in t for t in group_texts)
    assert not [m for m in env.session.messages(ADMIN_TG) if "N7" in (m.text or "")]
    assert any("N7" in (m.text or "") for m in env.session.messages(CLIENT_TG))


async def test_showcase_link_in_its_topic_makes_a_draft(env, monkeypatch):
    from crm.domain.models import ShowcaseItem

    await env.bind_all()
    added = []

    def fake_add(actor, url):
        added.append(url)
        return ShowcaseItem(
            id="sc1", url=url, shop="ssg", brand="The North Face", model="Hailstone Jacket"
        )

    monkeypatch.setattr(env.services.showcase, "add", fake_add)
    await env.say("🛍 Ветрина", "https://www.ssg.com/item/1")
    assert added == ["https://www.ssg.com/item/1"]
    await env.say("📣 Уведомления", "https://www.ssg.com/item/2")  # not the showcase topic
    assert added == ["https://www.ssg.com/item/1"]
    edits = [m for m in env.session.sent if type(m).__name__ == "EditMessageText"]
    button = edits[-1].reply_markup.inline_keyboard[0][0]
    assert button.url == "https://t.me/crm_bot?startapp=prep-sc1"


async def test_a_shop_refusing_the_bot_is_tried_again_later(env, monkeypatch):
    """The owner (02.11.2026): SSG refused after ~10 links; the bot retries alone."""
    import asyncio

    from crm.bot.handlers import showcase as handler
    from crm.domain.models import ShowcaseItem
    from crm.services.showcase_service import ShopBlockedError

    await env.bind_all()
    calls = []

    def flaky_add(actor, url):
        calls.append(url)
        if len(calls) < 3:
            raise ShopBlockedError()
        return ShowcaseItem(id="sc9", url=url, shop="SSG.com", brand="Nike", model="Bag")

    monkeypatch.setattr(env.services.showcase, "add", flaky_add)
    monkeypatch.setattr(handler, "RETRY_DELAYS", (0, 0, 0))
    await env.say("🛍 Ветрина", "https://www.ssg.com/item/9")
    await asyncio.gather(*list(handler._retries))
    assert len(calls) == 3
    edits = [m.text for m in env.session.sent if type(m).__name__ == "EditMessageText"]
    assert any("Попробую ещё раз" in t for t in edits)
    assert "Черновик витрины" in edits[-1]


async def test_links_are_read_one_by_one_with_a_random_pause(monkeypatch):
    """The owner (02.11.2026): «каждую ссылку с разной периодичностью, 25, 30 секунд»."""
    import asyncio

    from crm.bot.handlers import showcase as handler

    monkeypatch.setattr(handler, "LINK_GAP_SECONDS", (0.05, 0.08))
    queue = handler.LinkQueue()
    loop = asyncio.get_running_loop()
    starts = []

    async def read(i):
        async with queue.turn():
            starts.append((i, loop.time()))
            await asyncio.sleep(0.01)

    await asyncio.gather(*(read(i) for i in range(3)))
    assert [i for i, _ in starts] == [0, 1, 2]  # in the order sent
    gaps = [b - a for (_, a), (_, b) in zip(starts, starts[1:], strict=False)]
    assert all(0.06 - 0.005 <= g <= 0.09 + 0.03 for g in gaps)

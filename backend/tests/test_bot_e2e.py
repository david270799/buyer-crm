"""End-to-end bot tests: real aiogram Dispatcher, fake Telegram network.

Updates go through the access middleware, role filters, handlers, services
and the database; outgoing Bot API calls are recorded instead of sent.
"""

from datetime import datetime, timezone
from itertools import count

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import GetMe, SendMessage, TelegramMethod
from aiogram.types import Chat, Message, Update, User
from conftest import ADMIN_TG, CLIENT_TG, START_BALANCE, balance, seed_order

from crm.bot.app import create_dispatcher
from crm.config import Settings

GROUP_ID = -100500
_ids = count(1)


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent: list[TelegramMethod] = []

    async def make_request(self, bot, method, timeout=None):
        self.sent.append(method)
        if isinstance(method, GetMe):
            return User(id=42, is_bot=True, first_name="CRM", username="crm_bot")
        if isinstance(method, SendMessage):
            return Message(
                message_id=next(_ids),
                date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - unused
        raise NotImplementedError
        yield b""

    async def close(self):
        pass

    def texts(self) -> list[str]:
        return [m.text for m in self.sent if isinstance(m, SendMessage)]


@pytest.fixture
def bot_env(db, services, client_doc):
    settings = Settings(
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
    session = RecordingSession()
    bot = Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = create_dispatcher(services, settings)

    async def send(
        text: str,
        user_id: int = ADMIN_TG,
        chat_id: int | None = None,
        message_id: int | None = None,
    ) -> list[str]:
        chat_id = user_id if chat_id is None else chat_id
        chat_type = "private" if chat_id > 0 else "supergroup"
        update = Update(
            update_id=next(_ids),
            message=Message(
                message_id=message_id or next(_ids),
                date=datetime.now(timezone.utc),
                chat=Chat(id=chat_id, type=chat_type),
                from_user=User(id=user_id, is_bot=False, first_name="U"),
                text=text,
            ),
        )
        before = len(session.texts())
        await dp.feed_update(bot, update)
        return session.texts()[before:]

    return send


async def test_admin_buy_command_charges_balance(db, bot_env):
    seed_order(db, "n5")

    (reply,) = await bot_env("/buy 5 140,000 170000")

    assert "✅ Заказ <b>n5</b> выкуплен" in reply
    assert "₩ 830,000" in reply
    assert balance(db) == START_BALANCE - 170_000


async def test_repeated_buy_command_reports_no_second_charge(db, bot_env):
    seed_order(db, "n5")
    await bot_env("/buy 5 140000 170000")

    (reply,) = await bot_env("/buy n5 140000 170000")

    assert "Повторного списания нет" in reply
    assert balance(db) == START_BALANCE - 170_000


async def test_client_cannot_run_admin_commands(db, bot_env):
    seed_order(db, "n5")

    replies = await bot_env("/buy 5 1 2", user_id=CLIENT_TG, chat_id=GROUP_ID)

    assert replies == []
    assert db.get("orders", "n5")["status"] == "new"


async def test_stranger_is_ignored_in_group_and_gets_id_in_private(db, bot_env):
    assert await bot_env("/balance", user_id=777, chat_id=GROUP_ID) == []
    (reply,) = await bot_env("/start", user_id=777)
    assert "закрытая" in reply and "777" in reply


async def test_client_sees_order_without_purchase_price(db, bot_env):
    seed_order(
        db,
        "n5",
        status="bought",
        purchase_price=140_000,
        client_price=170_000,
        profit=30_000,
        internal_comment="продавец тянет",
        client_comment="Скоро",
    )

    (client_reply,) = await bot_env("/order 5", user_id=CLIENT_TG)
    (admin_reply,) = await bot_env("/order 5")

    assert "₩ 170,000" in client_reply and "Скоро" in client_reply
    for secret in ("140,000", "30,000", "продавец", "Закупка", "Прибыль"):
        assert secret not in client_reply
    assert "₩ 140,000" in admin_reply and "продавец тянет" in admin_reply


async def test_cargo_command_reports_updated_and_missing(db, bot_env):
    for order_id in ("n5", "n10"):
        seed_order(db, order_id, status="bought", client_price=1, charged_amount_krw=1)

    (reply,) = await bot_env("/cargo TRK777 5 10 23", chat_id=GROUP_ID)

    assert "SHP-2026-001" in reply
    assert "✅ Обновлено: n5, n10" in reply
    assert "⚠️ Не найдено: n23" in reply


async def test_validation_error_is_shown_without_stack_trace(db, bot_env):
    (reply,) = await bot_env("/buy 5 abc 170000")
    assert reply.startswith("❌ Некорректная сумма")
    assert "Traceback" not in reply


async def test_domain_error_message(db, bot_env):
    (reply,) = await bot_env("/cancel 404")
    assert reply == "❌ Заказ n404 не найден."


async def test_deposit_is_idempotent_per_telegram_message(db, bot_env):
    await bot_env("/deposit 500000 перевод", message_id=900)
    (reply,) = await bot_env("/deposit 500000 перевод", message_id=900)

    assert "уже была проведена" in reply
    assert balance(db) == START_BALANCE + 500_000


async def test_balance_for_client_with_rate(db, bot_env):
    await bot_env("/rate 1000")
    (reply,) = await bot_env("/balance", user_id=CLIENT_TG)
    assert "₩ 1,000,000" in reply and "$ 1,000" in reply


async def test_user_text_is_escaped(db, bot_env):
    await bot_env("/deposit 1000 <b>x</b>")
    (reply,) = await bot_env("/history")
    assert "&lt;b&gt;x&lt;/b&gt;" in reply


async def test_status_command(db, bot_env):
    seed_order(db, "n1", status="bought", client_price=1)
    (reply,) = await bot_env("/status склад 1, 2")
    assert "✅ Обновлено: n1" in reply and "Не найдено: n2" in reply


async def test_invalid_token_gives_clear_error_and_closes_session(services):
    from aiogram.exceptions import TelegramUnauthorizedError

    from crm.bot.app import run_bot
    from crm.domain.errors import ConfigurationError

    class UnauthorizedSession(RecordingSession):
        closed = False

        async def make_request(self, bot, method, timeout=None):
            raise TelegramUnauthorizedError(method=method, message="Unauthorized")

        async def close(self):
            self.closed = True

    session = UnauthorizedSession()
    settings = Settings(
        bot_token="1:bad",
        admin_ids=frozenset({ADMIN_TG}),
        allowed_chat_ids=frozenset(),
        firebase_project_id=None,
        firebase_credentials_path=None,
        firebase_credentials_json=None,
        firebase_storage_bucket=None,
        gemini_api_key=None,
        log_level="INFO",
    )
    with pytest.raises(ConfigurationError, match="BOT_TOKEN недействителен"):
        await run_bot(Bot("1:bad", session=session), services, settings)
    assert session.closed


async def test_admin_replies_in_group_use_client_visibility(db, bot_env):
    seed_order(
        db,
        "n5",
        status="bought",
        purchase_price=140_000,
        client_price=170_000,
        profit=30_000,
        charged_amount_krw=170_000,
        internal_comment="секрет",
    )
    seed_order(db, "n6")

    (order_reply,) = await bot_env("/order 5", chat_id=GROUP_ID)
    (buy_reply,) = await bot_env("/buy 6 90000 120000", chat_id=GROUP_ID)
    (private_buy,) = await bot_env("/order 6")

    for reply in (order_reply, buy_reply):
        for secret in ("140,000", "90,000", "Закупка", "Прибыль", "секрет"):
            assert secret not in reply
    assert "₩ 120,000" in buy_reply
    assert "Закупка: ₩ 90,000" in private_buy


async def test_demo_data_supports_the_whole_flow():
    from crm.demo import DEMO_BALANCE, create_demo_database
    from crm.services.container import build_services

    db = create_demo_database(client_telegram_id=CLIENT_TG)
    services = build_services(db, frozenset({ADMIN_TG}))
    admin = services.roles.resolve(ADMIN_TG)
    assert services.roles.resolve(CLIENT_TG) is not None

    from crm.services.common import Actor

    actor = Actor.telegram(ADMIN_TG, admin)
    services.orders.buy(actor, "121", 150_000, 180_000)
    services.shipments.ship_orders(actor, ["123", "124", "125"], "DEMO123")
    services.orders.cancel(actor, "122")

    assert db.get("client_info", "main_client")["balance"] == DEMO_BALANCE - 180_000
    assert db.get("orders", "n124")["shipment_id"].startswith("SHP-")
    assert services.orders.cancel(actor, "121").refunded_krw == 180_000

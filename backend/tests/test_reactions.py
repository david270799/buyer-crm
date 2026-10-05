"""Reactions on the client's order photo follow the order status."""

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SetMessageReaction
from conftest import seed_order

from crm.bot.reactions import ReactionSyncer
from crm.domain.enums import OrderStatus

pytestmark = pytest.mark.usefixtures("client_doc")

GROUP = -100777


class FakeTelegram(BaseSession):
    """Accepts standard reactions only, like Telegram does for bots."""

    allowed = {"👍", "👌", "🕊", "💯"}

    def __init__(self):
        super().__init__()
        self.calls: list[tuple[int, int, list[str]]] = []

    async def make_request(self, bot, method, timeout=None):
        assert isinstance(method, SetMessageReaction)
        emojis = [r.emoji for r in method.reaction or []]
        self.calls.append((method.chat_id, method.message_id, emojis))
        if any(e not in self.allowed for e in emojis):
            raise TelegramBadRequest(method, "Bad Request: REACTION_INVALID")
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError
        yield b""

    async def close(self):
        pass


@pytest.fixture
def telegram():
    return FakeTelegram()


@pytest.fixture
def syncer(services, telegram):
    bot = Bot("42:TEST", session=telegram)
    return ReactionSyncer(bot, services.reactions, pause_seconds=0)


def _photo_order(db, order_id: str, message_id: int, **fields):
    seed_order(db, order_id, source_chat_id=GROUP, source_message_id=message_id, **fields)


async def test_reaction_follows_status_with_fallbacks(db, services, admin, syncer, telegram):
    _photo_order(db, "N1", 11)
    _photo_order(db, "N2", 12)
    seed_order(db, "N3")  # made in the Mini App: no message, no reaction

    assert await syncer.run_once() == 0  # new orders: no reaction
    assert telegram.calls == []

    services.orders.buy(admin, "N1", 100, 120)
    await syncer.run_once()
    assert telegram.calls == [(GROUP, 11, ["👍"])]
    assert await syncer.run_once() == 0  # nothing changed: no second call

    telegram.calls.clear()
    services.orders.set_status(admin, ["N1"], OrderStatus.WAREHOUSE)
    await syncer.run_once()
    # 🏠 is not a Telegram reaction: the fallback 👌 is used.
    assert telegram.calls == [(GROUP, 11, ["🏠"]), (GROUP, 11, ["👌"])]
    assert db.get("reactions", f"tg{GROUP}_11")["emoji"] == "👌"


async def test_delivered_and_shipped_use_fallbacks(db, syncer, telegram):
    _photo_order(db, "N1", 11, status="cargo", shipment_id="SHP-2026-001")
    _photo_order(db, "N2", 12, status="delivered", shipment_id="SHP-2026-001")
    await syncer.run_once()
    shown = {(m, e[0]) for _, m, e in telegram.calls if e and e[0] in FakeTelegram.allowed}
    assert shown == {(11, "🕊"), (12, "💯")}


async def test_cancel_and_delete_remove_the_reaction(db, services, admin, syncer, telegram):
    _photo_order(db, "N1", 11)
    _photo_order(db, "N2", 12)
    services.orders.buy(admin, "N1", 100, 120)
    services.orders.buy(admin, "N2", 100, 120)
    await syncer.run_once()
    telegram.calls.clear()

    services.orders.cancel(admin, "N1")
    services.orders.delete_orders(admin, ["N2"])
    await syncer.run_once()

    assert sorted(telegram.calls) == [(GROUP, 11, []), (GROUP, 12, [])]
    assert db.query("reactions") == []
    telegram.calls.clear()
    assert await syncer.run_once() == 0


async def test_a_reaction_telegram_refuses_is_not_retried(db, syncer, telegram):
    telegram.allowed = set()  # the group allows no reactions at all
    _photo_order(db, "N1", 11, status="bought", charged_amount_krw=1, client_price=1)
    await syncer.run_once()
    assert len(telegram.calls) == 1
    assert "недоступна" in db.get("reactions", f"tg{GROUP}_11")["error"]
    await syncer.run_once()
    assert len(telegram.calls) == 1

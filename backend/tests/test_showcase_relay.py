"""«Витрина» orders: the admin is told privately and the card's photo with the
size goes to the orders channel (the owner, 05.11.2026)."""

# ruff: noqa: F811 - `showcase` is a fixture from test_showcase

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from conftest import ADMIN_TG, seed_order
from test_showcase import URL, showcase  # noqa: F401 - the fixture

from crm.bot.showcase_relay import ShowcaseRelay
from crm.services.showcase_service import CartLine

pytestmark = pytest.mark.usefixtures("client_doc")
CHANNEL = -1001234567890


class FakeBot:
    def __init__(self):
        self.sent = []
        self._ids = iter(range(700, 800))

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
        self.sent.append(("photo", chat_id, caption))
        return SimpleNamespace(message_id=next(self._ids))

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append(("text", chat_id, text))
        return SimpleNamespace(message_id=next(self._ids))


class FakeImages:
    def read(self, url):
        return b"jpeg" if url else None


def relay(services, bot):
    return ShowcaseRelay(bot, services.showcase_relay, FakeImages(), frozenset({ADMIN_TG}), None)


async def test_showcase_order_goes_to_the_admin_and_the_channel(
    db,
    services,
    showcase,
    admin,
    client_actor,
):
    # The channel orders come from: the latest photo order.
    seed_order(
        db,
        "N1",
        source_chat_id=CHANNEL,
        source_message_id=5,
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    item = showcase.add(admin, URL)
    showcase.set_status(admin, item.id, "published")
    [order] = showcase.order(client_actor, [CartLine(item.id, "M")])

    bot = FakeBot()
    assert await relay(services, bot).run_once() == 1
    kinds = [(kind, chat) for kind, chat, _ in bot.sent]
    assert kinds == [("photo", CHANNEL), ("photo", ADMIN_TG)]
    assert "Размер: <b>M</b>" in bot.sent[0][2] and "₩" not in bot.sent[0][2]
    assert f"Заказ из витрины · {order.id}" in bot.sent[1][2]
    assert "Заказал клиент" in bot.sent[1][2] and "отправлено в канал" in bot.sent[1][2]

    stored = db.get("orders", order.id)
    assert stored["relay"] == "sent"
    assert (stored["source_chat_id"], stored["source_message_id"]) == (CHANNEL, 700)
    # The post now carries the order's reaction like any photo order (👍 once bought).
    db.run_transaction(lambda tx: tx.update("orders", order.id, {"status": "bought"}))
    assert any(t.order_id == order.id for t in services.reactions.pending())
    assert await relay(services, bot).run_once() == 0  # never twice
    assert len(bot.sent) == 2


async def test_no_known_channel_still_tells_the_admin(db, services, showcase, admin):
    item = showcase.add(admin, URL)
    showcase.set_status(admin, item.id, "published")
    [order] = showcase.order(admin, [CartLine(item.id, "M")])
    bot = FakeBot()
    await relay(services, bot).run_once()
    assert [chat for _, chat, _ in bot.sent] == [ADMIN_TG]
    assert "не знаю, какой это канал" in bot.sent[0][2]
    assert db.get("orders", order.id).get("source_message_id") is None


def test_plain_orders_are_not_relayed(db, services, admin):
    from crm.services.order_service import NewOrder

    services.orders.create_order(admin, NewOrder(brand="Nike", model="Dunk", size="270"))
    assert services.showcase_relay.pending() == []

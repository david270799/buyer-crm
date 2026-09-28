"""Telegram notifications: who gets what, outbox bookkeeping, the sender."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from itertools import count

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message
from conftest import ADMIN_TG, CLIENT_TG, seed, seed_order

from crm.bot.notifier import TelegramNotifier, open_url
from crm.domain.errors import PermissionDeniedError, ValidationError
from crm.domain.events import Event
from crm.services.container import build_services
from crm.services.notifications import MAX_ATTEMPTS, SendOutcome

pytestmark = pytest.mark.usefixtures("client_doc")

SECOND_ADMIN = 1002
_ids = count(1)


def deliveries(db) -> dict[str, str | None]:
    """event type → delivery status (types are unique within each test)."""
    return {data["type"]: data.get("delivery") for _, data in db.query("events")}


def enable(services, admin, recipient="admins", level="important"):
    return services.notifications.update_settings(admin, recipient=recipient, level=level)


# --- who gets what ---------------------------------------------------------


def test_off_by_default_nothing_is_sent_and_backlog_is_skipped(db, services, admin):
    seed_order(db, "N5")
    services.orders.buy(admin, "5", 140_000, 170_000)

    assert services.notifications.due().deliveries == []
    assert deliveries(db) == {"order_bought": "skipped"}

    enable(services, admin, level="all")
    assert services.notifications.due().deliveries == []  # skipped earlier stays skipped


def test_events_before_switching_on_are_never_sent(db, services, admin):
    seed_order(db, "N5")
    services.orders.buy(admin, "5", 140_000, 170_000)  # pending, sender not running yet
    enable(services, admin, level="all")
    services.orders.cancel(admin, "5")

    batch = services.notifications.due()

    assert [d.event.type for d in batch.deliveries] == ["order_cancelled"]
    assert deliveries(db)["order_bought"] == "skipped"


def test_important_level_skips_normal_events(db, services, admin):
    seed_order(db, "N5")
    enable(services, admin)
    services.orders.buy(admin, "5", 140_000, 170_000)
    services.orders.cancel(admin, "5")

    batch = services.notifications.due()

    assert [(d.event.type, d.chat_ids) for d in batch.deliveries] == [
        ("order_cancelled", (ADMIN_TG,))
    ]
    assert deliveries(db)["order_bought"] == "skipped"


def test_client_recipient_uses_the_client_telegram_id(db, services, admin):
    seed_order(db, "N5")
    enable(services, admin, recipient="client", level="all")
    services.orders.buy(admin, "5", 140_000, 170_000)

    assert [d.chat_ids for d in services.notifications.due().deliveries] == [(CLIENT_TG,)]


def test_client_without_telegram_id_gets_nothing(db, services, admin):
    seed(db, "client_info", "main_client", {"name": "Клиент", "balance": 1_000_000})
    seed_order(db, "N5")
    enable(services, admin, recipient="client", level="all")
    services.orders.buy(admin, "5", 140_000, 170_000)

    assert services.notifications.due().deliveries == []
    assert deliveries(db) == {"order_bought": "skipped"}
    assert services.notifications.client_has_telegram(admin) is False


def test_stale_events_are_skipped(db, services, admin, clock):
    seed_order(db, "N5")
    enable(services, admin, level="all")
    services.orders.buy(admin, "5", 140_000, 170_000)
    clock.current += timedelta(hours=25)  # e.g. the bot was down for a day

    assert services.notifications.due().deliveries == []
    assert deliveries(db) == {"order_bought": "skipped"}


# --- outcomes ----------------------------------------------------------------


def _single(services, db, admin):
    seed_order(db, "N5")
    enable(services, admin, level="all")
    services.orders.buy(admin, "5", 140_000, 170_000)
    [delivery] = services.notifications.due().deliveries
    return delivery


def test_sent_is_recorded_and_not_sent_again(db, services, admin):
    delivery = _single(services, db, admin)

    services.notifications.record(delivery, [SendOutcome(ADMIN_TG, ok=True)])

    assert services.notifications.due().deliveries == []
    assert deliveries(db) == {"order_bought": "sent"}
    assert services.notifications.get_settings(admin).last_sent_at is not None


def test_network_errors_are_retried_then_given_up(db, services, admin):
    delivery = _single(services, db, admin)
    for _ in range(MAX_ATTEMPTS - 1):
        services.notifications.record(delivery, [SendOutcome(ADMIN_TG, ok=False, error="сеть")])
        [delivery] = services.notifications.due().deliveries

    services.notifications.record(delivery, [SendOutcome(ADMIN_TG, ok=False, error="сеть")])

    assert services.notifications.due().deliveries == []
    assert deliveries(db) == {"order_bought": "failed"}
    settings = services.notifications.get_settings(admin)
    assert settings.has_recent_error and settings.last_error == "сеть"


def test_blocked_bot_fails_at_once(db, services, admin):
    delivery = _single(services, db, admin)

    services.notifications.record(
        delivery, [SendOutcome(ADMIN_TG, ok=False, permanent=True, error="не открыл бота")]
    )

    assert deliveries(db) == {"order_bought": "failed"}


def test_partial_delivery_retries_only_the_missing_chat(db, clock, admin):
    services = build_services(db, frozenset({ADMIN_TG, SECOND_ADMIN}), clock)
    delivery = _single(services, db, admin)
    assert delivery.chat_ids == (ADMIN_TG, SECOND_ADMIN)

    services.notifications.record(
        delivery,
        [SendOutcome(ADMIN_TG, ok=True), SendOutcome(SECOND_ADMIN, ok=False, error="сеть")],
    )

    [retry] = services.notifications.due().deliveries
    assert retry.chat_ids == (SECOND_ADMIN,)


# --- settings ----------------------------------------------------------------


def test_settings_are_admin_only_validated_and_audited(db, services, admin, client_actor):
    with pytest.raises(PermissionDeniedError):
        services.notifications.update_settings(client_actor, recipient="client")
    with pytest.raises(PermissionDeniedError):
        services.notifications.get_settings(client_actor)
    with pytest.raises(ValidationError):
        services.notifications.update_settings(admin, recipient="everyone")

    first = enable(services, admin)
    same = enable(services, admin)
    level_only = services.notifications.update_settings(admin, level="all")

    assert same.since == first.since == level_only.since  # only a new recipient resets it
    actions = [d["action"] for _, d in db.query("audit_logs")]
    assert actions.count("settings.notifications") == 2


def test_delivery_fields_never_reach_the_feed(db, services, admin, client_actor):
    delivery = _single(services, db, admin)
    services.notifications.record(delivery, [SendOutcome(ADMIN_TG, ok=True)])

    from crm.api.app import event_json

    [event] = services.events.feed(client_actor)
    assert set(event_json(event)) == {
        "id",
        "type",
        "important",
        "title",
        "body",
        "order_ids",
        "shipment_id",
        "amount_krw",
        "created_at",
    }


def test_a_failing_listener_never_breaks_the_operation(db, services, admin):
    def broken():
        raise RuntimeError("boom")

    services.notifications.listen(broken)
    seed_order(db, "N5")

    services.orders.buy(admin, "5", 140_000, 170_000)

    assert db.get("orders", "N5")["status"] == "bought"


# --- the sender ----------------------------------------------------------------


class FakeTelegram(BaseSession):
    def __init__(self, errors: dict[int, list[Callable[[SendMessage], Exception]]] | None = None):
        super().__init__()
        self.sent: list[SendMessage] = []
        self.errors = errors or {}

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, SendMessage):
            queue = self.errors.get(method.chat_id)
            if queue:
                raise queue.pop(0)(method)
            self.sent.append(method)
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


def _bot(session: FakeTelegram) -> Bot:
    return Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def _notifier(session, services, url="https://crm.example.com"):
    return TelegramNotifier(
        _bot(session), services.notifications, url, settle_seconds=0, pause_seconds=0
    )


async def test_sender_delivers_text_with_mini_app_button(db, services, admin):
    session = FakeTelegram()
    seed_order(db, "N5", brand="Nike")
    enable(services, admin)
    services.orders.buy(admin, "5", 140_000, 170_000)
    services.orders.cancel(admin, "5")

    assert await _notifier(session, services).run_once() == 1

    [message] = session.sent
    assert message.chat_id == ADMIN_TG
    assert "N5" in message.text and "отмен" in message.text
    assert "140" not in message.text  # purchase price never appears
    button = message.reply_markup.inline_keyboard[0][0]
    assert button.web_app.url == "https://crm.example.com/?open=order%3AN5"
    assert await _notifier(session, services).run_once() == 0  # nothing twice


async def test_sender_without_mini_app_url_sends_plain_text(db, services, admin):
    session = FakeTelegram()
    _single(services, db, admin)

    await _notifier(session, services, url=None).run_once()

    assert session.sent[0].reply_markup is None


async def test_rejected_button_does_not_lose_the_notification(db, services, admin):
    def bad_button(method):
        return TelegramBadRequest(method=method, message="Bad Request: BUTTON_TYPE_INVALID")

    session = FakeTelegram({ADMIN_TG: [bad_button]})
    _single(services, db, admin)

    await _notifier(session, services).run_once()

    assert len(session.sent) == 1 and session.sent[0].reply_markup is None
    assert deliveries(db) == {"order_bought": "sent"}


async def test_blocked_bot_is_reported_in_settings(db, services, admin):
    def blocked(method):
        return TelegramForbiddenError(method=method, message="Forbidden: bot was blocked")

    session = FakeTelegram({ADMIN_TG: [blocked]})
    _single(services, db, admin)

    await _notifier(session, services).run_once()

    assert deliveries(db) == {"order_bought": "failed"}
    assert "Start" in services.notifications.get_settings(admin).last_error


async def test_network_error_is_retried_on_the_next_round(db, services, admin):
    def offline(method):
        return TelegramNetworkError(method=method, message="timeout")

    session = FakeTelegram({ADMIN_TG: [offline]})
    _single(services, db, admin)
    notifier = _notifier(session, services)

    await notifier.run_once()
    assert session.sent == [] and deliveries(db) == {"order_bought": "pending"}
    await notifier.run_once()
    assert len(session.sent) == 1 and deliveries(db) == {"order_bought": "sent"}


async def test_sender_wakes_up_when_an_event_is_recorded(db, services, admin):
    session = FakeTelegram()
    seed_order(db, "N5")
    enable(services, admin, level="all")
    notifier = TelegramNotifier(
        _bot(session), services.notifications, None, poll_seconds=60, settle_seconds=0
    )
    task = asyncio.create_task(notifier.run())
    try:
        await asyncio.sleep(0.05)
        await asyncio.to_thread(services.orders.buy, admin, "5", 140_000, 170_000)
        for _ in range(100):
            if session.sent:
                break
            await asyncio.sleep(0.05)
        assert len(session.sent) == 1
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_open_url_targets():
    order = Event("e1", None, False, "t", None, order_ids=["N5"])
    shipment = Event("e2", None, False, "t", None, order_ids=["N1", "N2"], shipment_id="SHP-1")
    general = Event("e3", None, False, "t", None)

    assert open_url("https://crm.example.com", order) == "https://crm.example.com/?open=order%3AN5"
    assert (
        open_url("https://x.io/app?v=2", shipment) == "https://x.io/app?v=2&open=shipment%3ASHP-1"
    )
    assert open_url("https://x.io/", general) == "https://x.io/?open=notifications"

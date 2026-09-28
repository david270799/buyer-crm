from decimal import Decimal

import pytest
from conftest import START_BALANCE, balance, ledger_entries, seed, seed_order

from crm.domain.errors import (
    ConfigurationError,
    ConflictError,
    PermissionDeniedError,
    ValidationError,
)
from crm.domain.money import format_usd

pytestmark = pytest.mark.usefixtures("client_doc")


def test_deposit_increases_balance_and_writes_ledger(db, services, admin):
    result = services.finance.deposit(admin, 5_000_000, "Перевод")

    assert not result.already_done
    assert balance(db) == START_BALANCE + 5_000_000
    entry = ledger_entries(db)[result.entry.id]
    assert entry["type"] == "deposit"
    assert entry["amount_krw"] == 5_000_000
    assert entry["balance_before"] == START_BALANCE
    assert entry["balance_after"] == START_BALANCE + 5_000_000
    assert entry["comment"] == "Перевод"


def test_deposit_with_same_idempotency_key_is_applied_once(db, services, admin):
    first = services.finance.deposit(admin, 500_000, idempotency_key="tg-100_42")
    second = services.finance.deposit(admin, 500_000, idempotency_key="tg-100_42")

    assert not first.already_done and second.already_done
    assert second.entry.id == first.entry.id == "deposit_tg-100_42"
    assert balance(db) == START_BALANCE + 500_000
    with pytest.raises(ConflictError):
        services.finance.deposit(admin, 600_000, idempotency_key="tg-100_42")


@pytest.mark.parametrize("amount", [0, -5])
def test_deposit_must_be_positive(db, services, admin, amount):
    with pytest.raises(ValidationError):
        services.finance.deposit(admin, amount)


def test_adjust_needs_comment_and_can_be_negative(db, services, admin):
    with pytest.raises(ValidationError, match="комментарий"):
        services.finance.adjust(admin, -10_000, "  ")
    with pytest.raises(ValidationError):
        services.finance.adjust(admin, 0, "x")

    services.finance.adjust(admin, -10_000, "Комиссия банка")

    assert balance(db) == START_BALANCE - 10_000
    (entry,) = ledger_entries(db).values()
    assert entry["type"] == "adjustment" and entry["amount_krw"] == -10_000


def test_ledger_reconstructs_balance(db, services, admin):
    seed_order(db, "N1")
    seed_order(db, "N2")
    services.finance.deposit(admin, 2_000_000)
    services.orders.buy(admin, "1", 100_000, 150_000)
    services.orders.buy(admin, "2", 200_000, 260_000)
    services.orders.cancel(admin, "2")
    services.finance.adjust(admin, -5_000, "Комиссия")

    entries = ledger_entries(db).values()
    assert START_BALANCE + sum(e["amount_krw"] for e in entries) == balance(db)
    history = services.finance.history(admin)
    assert [e.type.value for e in history] == [
        "adjustment",
        "order_refund",
        "order_charge",
        "order_charge",
        "deposit",
    ]
    # Each entry continues from the previous one.
    for newer, older in zip(history, history[1:], strict=False):
        assert newer.balance_before == older.balance_after


def test_balance_in_usd(db, services, admin, client_actor):
    seed(db, "client_info", "main_client", {"telegram_id": 1, "balance": 12_500_000})
    assert services.finance.get_balance(client_actor).balance_usd is None

    services.finance.set_rate(admin, Decimal("1350"))

    view = services.finance.get_balance(client_actor)
    assert view.balance_krw == 12_500_000
    assert format_usd(view.balance_usd) == "$ 9,259"
    assert db.get("settings", "general")["krw_per_usd"] == 1350


def test_fractional_rate_is_stored_as_number(db, services, admin):
    services.finance.set_rate(admin, Decimal("1352.5"))
    assert db.get("settings", "general")["krw_per_usd"] == 1352.5
    assert services.finance.get_settings(admin).krw_per_usd == Decimal("1352.5")


@pytest.mark.parametrize("rate", ["0", "99", "10001", "NaN"])
def test_rate_bounds(db, services, admin, rate):
    with pytest.raises(ValidationError):
        services.finance.set_rate(admin, Decimal(rate))


def test_client_can_read_but_not_write(db, services, client_actor):
    assert services.finance.get_balance(client_actor).balance_krw == START_BALANCE
    assert services.finance.history(client_actor) == []
    with pytest.raises(PermissionDeniedError):
        services.finance.deposit(client_actor, 1)
    with pytest.raises(PermissionDeniedError):
        services.finance.adjust(client_actor, 1, "x")
    with pytest.raises(PermissionDeniedError):
        services.finance.set_rate(client_actor, Decimal("1300"))


def test_missing_client_document_is_a_clear_error(db, services, admin):
    seed(db, "client_info", "main_client", {"telegram_id": 1, "balance": "много"})
    with pytest.raises(ConfigurationError):
        services.finance.deposit(admin, 1)

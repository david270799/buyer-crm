from decimal import Decimal

import pytest
from conftest import START_BALANCE, balance, ledger_entries, seed_order

from crm.domain.errors import PermissionDeniedError, ValidationError
from crm.services.order_service import NewOrder

pytestmark = pytest.mark.usefixtures("client_doc")


def test_discount_lowers_prices_and_refunds_what_was_paid(db, services, admin):
    services.orders.create_order(admin, NewOrder(brand="A", client_price=167_640))  # N1 new
    services.orders.create_order(admin, NewOrder(brand="B"))  # N2 no price
    services.orders.create_order(admin, NewOrder(brand="C"))  # N3
    services.orders.buy(admin, "N3", 100_000, 200_000)
    seed_order(db, "N4", status="cargo", client_price=50_000, shipment_id="SHP-2026-001")
    seed_order(db, "N5", status="cancelled", client_price=50_000)

    result = services.orders.discount(admin, ["1", "2", "3", "4", "5"], Decimal("10"), "k1")

    assert result.updated == [("N1", 167_640, 150_876), ("N3", 200_000, 180_000)]
    assert [i for i, _ in result.skipped] == ["N2", "N4", "N5"]
    assert result.refunded_krw == 20_000
    n3 = db.get("orders", "N3")
    assert (n3["client_price"], n3["charged_amount_krw"], n3["profit"]) == (
        180_000,
        180_000,
        80_000,
    )
    assert db.get("orders", "N1")["charged_amount_krw"] == 0  # not paid: price only
    assert balance(db) == START_BALANCE - 200_000 + 20_000
    entry = ledger_entries(db)["order_discount_N3_k1"]
    assert entry["amount_krw"] == 20_000 and entry["order_id"] == "N3"
    assert entry["comment"] == "Скидка 10%"
    events = services.events.for_order(admin, "N3")
    assert any(e.title.startswith("Скидка 10%") for e in events)


def test_repeated_discount_with_the_same_key_changes_nothing(db, services, admin):
    services.orders.create_order(admin, NewOrder(client_price=100_000))
    services.orders.discount(admin, ["N1"], Decimal("12.5"), "k1")
    again = services.orders.discount(admin, ["N1"], Decimal("12.5"), "k1")
    assert again.unchanged == ["N1"] and again.updated == []
    assert db.get("orders", "N1")["client_price"] == 87_500


def test_cancel_after_discount_refunds_the_rest_and_nets_to_zero(db, services, admin):
    services.orders.create_order(admin, NewOrder(client_price=0))
    services.orders.buy(admin, "N1", 100_000, 200_000)
    services.orders.discount(admin, ["N1"], Decimal("10"), "k1")
    services.orders.cancel(admin, "N1")
    assert balance(db) == START_BALANCE


def test_discount_validation_and_rights(db, services, admin, client_actor):
    seed_order(db, "N1", client_price=100)
    for bad in (Decimal("0"), Decimal("100"), Decimal("5.555")):
        with pytest.raises(ValidationError):
            services.orders.discount(admin, ["N1"], bad)
    with pytest.raises(PermissionDeniedError):
        services.orders.discount(client_actor, ["N1"], Decimal("10"))

"""Re-purchase: the shop cancelled, the item was bought elsewhere."""

import pytest
from conftest import START_BALANCE, balance, ledger_entries, seed_order

from crm.domain.enums import OrderStatus
from crm.domain.errors import ConflictError, PermissionDeniedError
from crm.services.shipment_service import ShipmentDetails

pytestmark = pytest.mark.usefixtures("client_doc")


def _bought(db, services, admin, order_id="n5", purchase=140_000, price=170_000):
    seed_order(db, order_id, brand="Nike", model="Dunk", source_url="https://shop-a.kr/1")
    services.orders.buy(admin, order_id, purchase, price)


def test_rebuy_with_higher_price_charges_only_the_difference(db, services, admin):
    _bought(db, services, admin)
    services.orders.set_status(admin, ["5"], OrderStatus.WAREHOUSE)

    result = services.orders.rebuy(
        admin, "5", 150_000, 185_000, source_url="https://shop-b.kr/2", reason="Нет в наличии"
    )

    assert not result.already_done
    assert result.change.amount_krw == -15_000
    assert balance(db) == START_BALANCE - 185_000
    entry = ledger_entries(db)["order_rebuy_n5_1"]
    assert entry["type"] == "order_rebuy" and entry["amount_krw"] == -15_000
    order = db.get("orders", "n5")
    assert order["status"] == "bought"  # bought again, not at the warehouse any more
    assert (order["purchase_price"], order["client_price"], order["profit"]) == (
        150_000,
        185_000,
        35_000,
    )
    assert order["charged_amount_krw"] == 185_000
    assert order["source_url"] == "https://shop-b.kr/2"
    assert order["rebuy_count"] == 1
    first, second = order["purchases"]
    assert first["purchase_price"] == 140_000 and first["replaced_at"] is not None
    assert first["source_url"] == "https://shop-a.kr/1"
    assert second["purchase_price"] == 150_000 and second["note"] == "Нет в наличии"


def test_rebuy_with_lower_price_refunds_the_difference(db, services, admin):
    _bought(db, services, admin)
    result = services.orders.rebuy(admin, "5", 120_000, 160_000)
    assert result.change.amount_krw == 10_000
    assert balance(db) == START_BALANCE - 160_000


def test_rebuy_with_same_client_price_moves_no_money(db, services, admin):
    _bought(db, services, admin)
    result = services.orders.rebuy(admin, "5", 145_000, 170_000, source_url="https://shop-b.kr/2")
    assert result.change is None
    assert balance(db) == START_BALANCE - 170_000
    assert [k for k in ledger_entries(db) if k.startswith("order_rebuy")] == []
    assert db.get("orders", "n5")["profit"] == 25_000


def test_repeating_the_same_rebuy_changes_nothing(db, services, admin):
    _bought(db, services, admin)
    services.orders.rebuy(admin, "5", 150_000, 185_000, source_url="https://shop-b.kr/2")

    again = services.orders.rebuy(admin, "5", 150_000, 185_000, source_url="https://shop-b.kr/2")

    assert again.already_done
    assert balance(db) == START_BALANCE - 185_000
    assert db.get("orders", "n5")["rebuy_count"] == 1


def test_second_rebuy_gets_its_own_ledger_entry(db, services, admin):
    _bought(db, services, admin)
    services.orders.rebuy(admin, "5", 150_000, 185_000)
    services.orders.rebuy(admin, "5", 155_000, 190_000)

    entries = ledger_entries(db)
    assert entries["order_rebuy_n5_1"]["amount_krw"] == -15_000
    assert entries["order_rebuy_n5_2"]["amount_krw"] == -5_000
    assert len(db.get("orders", "n5")["purchases"]) == 3
    assert START_BALANCE + sum(e["amount_krw"] for e in entries.values()) == balance(db)


def test_cancel_after_rebuy_refunds_what_is_charged_now(db, services, admin):
    _bought(db, services, admin)
    services.orders.rebuy(admin, "5", 150_000, 185_000)

    assert services.orders.cancel(admin, "5").refunded_krw == 185_000
    assert balance(db) == START_BALANCE


@pytest.mark.parametrize("status", ["new", "cancelled", "cargo", "delivered"])
def test_rebuy_is_refused_outside_bought_and_warehouse(db, services, admin, status):
    seed_order(db, "n5", status=status, client_price=10, charged_amount_krw=10)
    with pytest.raises(ConflictError):
        services.orders.rebuy(admin, "5", 1, 2)
    assert balance(db) == START_BALANCE


def test_rebuy_is_refused_for_shipped_orders_and_unrecorded_charges(db, services, admin):
    _bought(db, services, admin)
    services.shipments.ship_orders(admin, ["5"], None, ShipmentDetails())
    with pytest.raises(ConflictError):
        services.orders.rebuy(admin, "5", 1, 2)

    seed_order(db, "n6", status="bought", client_price=100)  # no charge recorded
    with pytest.raises(ConflictError, match="не записано"):
        services.orders.rebuy(admin, "6", 1, 2)


def test_rebuy_requires_admin(db, services, admin, client_actor):
    _bought(db, services, admin)
    with pytest.raises(PermissionDeniedError):
        services.orders.rebuy(client_actor, "5", 1, 2)


def test_buy_with_other_prices_points_to_rebuy(db, services, admin):
    _bought(db, services, admin)
    with pytest.raises(ConflictError, match="/rebuy"):
        services.orders.buy(admin, "5", 1, 2)

from decimal import Decimal

import pytest
from conftest import START_BALANCE, balance, ledger_entries, seed_order

from crm.domain.errors import ValidationError
from crm.services.shipment_service import ShipmentDetails, ShipmentUpdate

pytestmark = pytest.mark.usefixtures("client_doc")


def _ship(services, admin, db, watches, cost=95_000):
    for n in (1, 2):
        seed_order(db, f"N{n}", status="warehouse")
    return services.shipments.ship_orders(
        admin, ["N1", "N2"], "TRK1", ShipmentDetails(shipping_cost_krw=cost, watch_count=watches)
    )


def test_watches_are_a_separate_charge_after_shipping(db, services, admin):
    services.finance.set_rate(admin, Decimal("1350"))
    result = _ship(services, admin, db, 2)

    assert result.shipping_change.amount_krw == -95_000
    assert result.watch_change.amount_krw == -27_000  # 2 × $10 × 1350
    assert balance(db) == START_BALANCE - 95_000 - 27_000
    entries = ledger_entries(db)
    watch = entries[f"watch_charge_{result.shipment.id}_1"]
    assert watch["type"] == "watch_charge"
    assert watch["comment"] == "2 шт. × $10 = $20 · 1 $ = 1,350 ₩"
    # Shipping first, then watches.
    assert watch["balance_before"] == START_BALANCE - 95_000
    doc = db.get("shipments", result.shipment.id)
    assert doc["watch_count"] == 2 and doc["watch_charged_krw"] == 27_000


def test_rate_is_fixed_and_only_the_difference_moves(db, services, admin):
    services.finance.set_rate(admin, Decimal("1350"))
    shipment = _ship(services, admin, db, 2).shipment
    services.finance.set_rate(admin, Decimal("1500"))  # later rate changes do not matter

    more = services.shipments.update_shipment(admin, shipment.id, ShipmentUpdate(watch_count=3))
    assert more.watch_change.amount_krw == -13_500
    fewer = services.shipments.update_shipment(admin, shipment.id, ShipmentUpdate(watch_count=0))
    assert fewer.watch_change.amount_krw == 40_500
    assert balance(db) == START_BALANCE - 95_000
    # Same count again: nothing moves.
    same = services.shipments.update_shipment(
        admin, shipment.id, ShipmentUpdate(watch_count=0, comment="ok")
    )
    assert same.watch_change is None
    assert balance(db) == START_BALANCE - 95_000


def test_watches_need_a_rate(db, services, admin):
    with pytest.raises(ValidationError):
        _ship(services, admin, db, 1)
    assert balance(db) == START_BALANCE
    # Without watches no rate is needed.
    assert _ship(services, admin, db, 0).watch_change is None


def test_client_sees_the_watch_line(db, services, admin, client_actor):
    services.finance.set_rate(admin, Decimal("1350"))
    _ship(services, admin, db, 1)
    lines = [e for e in services.finance.history(client_actor) if e.type.value == "watch_charge"]
    assert len(lines) == 1 and lines[0].amount_krw == -13_500


def test_history_shows_watches_right_after_shipping(db, services, admin):
    services.finance.set_rate(admin, Decimal("1350"))
    _ship(services, admin, db, 1)
    newest = services.finance.history(admin, limit=2)
    assert [e.type.value for e in newest] == ["watch_charge", "shipping_charge"]

from datetime import datetime, timezone

import pytest
from conftest import START_BALANCE, audit_actions, balance, ledger_entries, seed, seed_order

from crm.domain.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from crm.services.shipment_service import ShipmentDetails, ShipmentUpdate

pytestmark = pytest.mark.usefixtures("client_doc")


def _bought(db, *order_ids, status="bought"):
    for order_id in order_ids:
        seed_order(
            db,
            order_id,
            status=status,
            client_price=100_000,
            purchase_price=80_000,
            charged_amount_krw=100_000,
        )


def test_cargo_creates_shipment_and_marks_orders(db, services, admin):
    _bought(db, "n5", "n10")
    _bought(db, "n18", status="warehouse")

    result = services.shipments.ship_orders(admin, ["5", "n10", "18", "23"], "trk123")

    assert result.created
    assert result.added == ["n5", "n10", "n18"]
    assert result.not_found == ["n23"]
    shipment = db.get("shipments", "SHP-2026-001")
    assert shipment["shipment_number"] == 1
    assert shipment["tracking_code"] == "TRK123"
    assert shipment["order_ids"] == ["n5", "n10", "n18"]
    assert shipment["created_by"] == admin.id
    for order_id in ("n5", "n10", "n18"):
        order = db.get("orders", order_id)
        assert order["status"] == "cargo"
        assert order["shipment_id"] == "SHP-2026-001"
        assert order["cargo_code"] == "TRK123"
        assert order["cargo_at"] is not None
    assert db.get("counters", "shipments")["next_id"] == 2
    assert audit_actions(db).count("order.ship") == 3
    assert "shipment.create" in audit_actions(db)


def test_repeating_cargo_command_changes_nothing(db, services, admin):
    _bought(db, "n5", "n10")
    services.shipments.ship_orders(admin, ["5", "10"], "TRK123")
    audit_before = len(audit_actions(db))

    again = services.shipments.ship_orders(admin, ["5", "10"], "trk123")

    assert not again.created
    assert again.added == []
    assert again.already_in_shipment == ["n5", "n10"]
    assert again.shipment.id == "SHP-2026-001"
    assert len(db.query("shipments")) == 1
    assert len(audit_actions(db)) == audit_before


def test_same_tracking_code_extends_existing_shipment(db, services, admin):
    _bought(db, "n5", "n6")
    services.shipments.ship_orders(admin, ["5"], "TRK123")

    result = services.shipments.ship_orders(admin, ["5", "6"], "TRK123")

    assert not result.created
    assert result.added == ["n6"]
    assert result.already_in_shipment == ["n5"]
    assert db.get("shipments", "SHP-2026-001")["order_ids"] == ["n5", "n6"]
    assert db.get("orders", "n6")["shipment_id"] == "SHP-2026-001"


def test_cargo_skips_orders_that_cannot_be_shipped(db, services, admin):
    seed_order(db, "n1", status="new")
    seed_order(db, "n2", status="cancelled")
    seed_order(db, "n3", status="delivered", client_price=1)
    _bought(db, "n4")
    services.shipments.ship_orders(admin, ["4"], "OTHER1")
    _bought(db, "n5")

    result = services.shipments.ship_orders(admin, ["1", "2", "3", "4", "5"], "TRK123")

    assert result.added == ["n5"]
    reasons = dict(result.skipped)
    assert set(reasons) == {"n1", "n2", "n3", "n4"}
    assert "SHP-2026-001" in reasons["n4"]
    assert db.get("orders", "n1")["status"] == "new"
    assert db.get("orders", "n4")["shipment_id"] == "SHP-2026-001"


def test_nothing_to_ship_creates_no_shipment(db, services, admin):
    seed_order(db, "n1", status="new")

    result = services.shipments.ship_orders(admin, ["1", "2"], "TRK123")

    assert result.shipment is None and not result.created
    assert db.query("shipments") == []
    assert db.get("counters", "shipments") is None


def test_second_shipment_gets_next_number(db, services, admin):
    _bought(db, "n1", "n2")
    services.shipments.ship_orders(admin, ["1"], "TRK-A")
    result = services.shipments.ship_orders(admin, ["2"], "TRK-B")
    assert result.shipment.id == "SHP-2026-002"
    assert result.shipment.shipment_number == 2


def test_cargo_order_without_shipment_is_attached(db, services, admin):
    seed_order(db, "n7", status="cargo", client_price=50_000, cargo_code="OLD1")

    result = services.shipments.ship_orders(admin, ["7"], "NEW1")

    assert result.added == ["n7"]
    order = db.get("orders", "n7")
    assert order["cargo_code"] == "NEW1"


def test_shipment_details_are_stored_and_cost_is_charged_once(db, services, admin):
    _bought(db, "n1")
    shipped_on = datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc)
    details = ShipmentDetails(
        box_number="B-18",
        weight_kg=12.5,
        shipping_cost_krw=95_000,
        shipment_date=shipped_on,
        comment="Хрупкое",
    )

    result = services.shipments.ship_orders(admin, ["1"], None, details)

    shipment = db.get("shipments", result.shipment.id)
    assert shipment["tracking_code"] is None
    assert shipment["box_number"] == "B-18"
    assert shipment["weight_kg"] == 12.5
    assert shipment["shipping_cost_krw"] == 95_000
    assert shipment["shipping_charged_krw"] == 95_000
    assert shipment["shipment_date"] == shipped_on
    assert shipment["comment"] == "Хрупкое"
    assert db.get("orders", "n1").get("cargo_code") is None
    assert balance(db) == START_BALANCE - 95_000
    entry = ledger_entries(db)[f"shipping_charge_{result.shipment.id}_1"]
    assert entry["type"] == "shipping_charge"
    assert entry["amount_krw"] == -95_000
    assert entry["shipment_id"] == result.shipment.id
    assert result.shipping_change.balance_after == START_BALANCE - 95_000


def test_repeating_cargo_with_cost_does_not_charge_again(db, services, admin):
    _bought(db, "n1", "n2")
    details = ShipmentDetails(shipping_cost_krw=50_000)
    services.shipments.ship_orders(admin, ["1"], "TRK1", details)

    services.shipments.ship_orders(admin, ["1"], "TRK1", details)  # nothing new
    services.shipments.ship_orders(admin, ["2"], "TRK1", details)  # same cost

    assert balance(db) == START_BALANCE - 50_000
    assert len(ledger_entries(db)) == 1


def test_changing_shipping_cost_charges_only_the_difference(db, services, admin):
    _bought(db, "n1")
    shipment = services.shipments.ship_orders(
        admin, ["1"], "TRK1", ShipmentDetails(shipping_cost_krw=50_000)
    ).shipment

    up = services.shipments.update_shipment(
        admin, shipment.id, ShipmentUpdate(shipping_cost_krw=80_000)
    )
    same = services.shipments.update_shipment(
        admin, shipment.id, ShipmentUpdate(shipping_cost_krw=80_000)
    )
    down = services.shipments.update_shipment(
        admin, shipment.id, ShipmentUpdate(shipping_cost_krw=60_000)
    )

    assert up.shipping_change.amount_krw == -30_000
    assert same.shipping_change is None
    assert down.shipping_change.amount_krw == 20_000
    assert balance(db) == START_BALANCE - 60_000
    doc = db.get("shipments", shipment.id)
    assert doc["shipping_cost_krw"] == 60_000
    assert doc["shipping_charged_krw"] == 60_000
    assert sorted(ledger_entries(db)) == [f"shipping_charge_{shipment.id}_{n}" for n in (1, 2, 3)]

    services.shipments.update_shipment(admin, shipment.id, ShipmentUpdate(shipping_cost_krw=None))
    assert balance(db) == START_BALANCE
    assert db.get("shipments", shipment.id)["shipping_charged_krw"] == 0


def test_cost_added_later_is_charged(db, services, admin):
    _bought(db, "n1")
    shipment = services.shipments.ship_orders(admin, ["1"], "TRK1").shipment
    assert balance(db) == START_BALANCE

    services.shipments.update_shipment(admin, shipment.id, ShipmentUpdate(shipping_cost_krw=70_000))

    assert balance(db) == START_BALANCE - 70_000


def test_update_details_without_money(db, services, admin):
    _bought(db, "n1", "n2")
    shipment = services.shipments.ship_orders(admin, ["1", "2"], "TRK1").shipment

    result = services.shipments.update_shipment(
        admin, shipment.id, ShipmentUpdate(tracking_code="new-trk", box_number="7", weight_kg=3)
    )

    assert result.shipping_change is None
    assert result.shipment.tracking_code == "NEW-TRK"
    assert db.get("orders", "n1")["cargo_code"] == "NEW-TRK"
    assert db.get("orders", "n2")["cargo_code"] == "NEW-TRK"
    assert db.get("shipments", shipment.id)["box_number"] == "7"
    assert ledger_entries(db) == {}


def test_update_tracking_to_one_used_elsewhere_is_refused(db, services, admin):
    _bought(db, "n1", "n2")
    services.shipments.ship_orders(admin, ["1"], "TRK1")
    second = services.shipments.ship_orders(admin, ["2"], "TRK2").shipment
    with pytest.raises(ConflictError, match="SHP-2026-001"):
        services.shipments.update_shipment(admin, second.id, ShipmentUpdate(tracking_code="trk1"))


def test_update_shipment_validation(db, services, admin, client_actor):
    with pytest.raises(ValidationError):
        services.shipments.update_shipment(admin, "SHP-2026-001", ShipmentUpdate())
    with pytest.raises(NotFoundError):
        services.shipments.update_shipment(admin, "SHP-2026-404", ShipmentUpdate(comment="x"))
    with pytest.raises(PermissionDeniedError):
        services.shipments.update_shipment(client_actor, "x", ShipmentUpdate(comment="x"))
    with pytest.raises(ValidationError):
        services.shipments.update_shipment(
            admin, "SHP-2026-001", ShipmentUpdate(shipping_cost_krw=-1)
        )


def test_ledger_still_reconstructs_balance_with_shipping(db, services, admin):
    _bought(db, "n1")
    shipment = services.shipments.ship_orders(
        admin, ["1"], "TRK1", ShipmentDetails(shipping_cost_krw=40_000)
    ).shipment
    services.shipments.update_shipment(admin, shipment.id, ShipmentUpdate(shipping_cost_krw=10_000))

    total = sum(e["amount_krw"] for e in ledger_entries(db).values())
    assert START_BALANCE + total == balance(db) == START_BALANCE - 10_000


def test_duplicate_tracking_in_data_is_reported(db, services, admin):
    seed(db, "shipments", "SHP-2026-001", {"tracking_code": "DUP1", "order_ids": []})
    seed(db, "shipments", "SHP-2026-002", {"tracking_code": "DUP1", "order_ids": []})
    _bought(db, "n1")
    with pytest.raises(ConflictError, match="нескольких отправках"):
        services.shipments.ship_orders(admin, ["1"], "DUP1")


@pytest.mark.parametrize("code", ["ab", "TRK 1", "трек123", "x" * 70])
def test_invalid_tracking_code(db, services, admin, code):
    with pytest.raises(ValidationError):
        services.shipments.ship_orders(admin, ["1"], code)


def test_invalid_weight(db, services, admin):
    with pytest.raises(ValidationError):
        services.shipments.ship_orders(admin, ["1"], None, ShipmentDetails(weight_kg=0))


def test_ship_requires_admin(db, services, client_actor):
    with pytest.raises(PermissionDeniedError):
        services.shipments.ship_orders(client_actor, ["1"], "TRK123")


def test_get_shipment_returns_orders(db, services, client_actor, admin):
    _bought(db, "n1", "n2")
    services.shipments.ship_orders(admin, ["1", "2"], "TRK123")

    shipment, orders = services.shipments.get_shipment(client_actor, "shp-2026-001")

    assert shipment.tracking_code == "TRK123"
    assert sorted(order.id for order in orders) == ["n1", "n2"]
    assert [s.id for s in services.shipments.list_shipments(client_actor)] == ["SHP-2026-001"]


def test_shipment_reference_by_number(db, services, admin, client_actor):
    _bought(db, "n1")
    services.shipments.ship_orders(admin, ["1"], "TRK1")
    shipment, _ = services.shipments.get_shipment(client_actor, "#1")
    assert shipment.id == "SHP-2026-001"
    assert services.shipments.resolve_id("1") == "SHP-2026-001"
    with pytest.raises(NotFoundError):
        services.shipments.resolve_id("99")

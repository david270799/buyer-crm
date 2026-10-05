import pytest
from conftest import START_BALANCE, balance, seed_order

from crm.domain.errors import PermissionDeniedError, ValidationError

pytestmark = pytest.mark.usefixtures("client_doc")


def _ship(services, admin):
    for n in (1, 2, 3):
        seed_order(services_db(services), f"N{n}", status="warehouse")
    return services.shipments.ship_orders(admin, ["N1", "N2", "N3"], "TRACK1").shipment


def services_db(services):
    return services.shipments._db


def test_split_moves_orders_to_a_new_shipment_without_money(db, services, admin):
    first = _ship(services, admin)

    part = services.shipments.split_shipment(admin, first.id, ["N3"], "TRACK2")

    assert part.id != first.id and part.order_ids == ["N3"]
    assert db.get("shipments", first.id)["order_ids"] == ["N1", "N2"]
    order = db.get("orders", "N3")
    assert order["shipment_id"] == part.id and order["cargo_code"] == "TRACK2"
    assert order["status"] == "cargo"
    assert balance(db) == START_BALANCE


def test_split_rules(db, services, admin, client_actor):
    first = _ship(services, admin)
    with pytest.raises(ValidationError):
        services.shipments.split_shipment(admin, first.id, ["N1", "N2", "N3"])
    with pytest.raises(ValidationError):
        services.shipments.split_shipment(admin, first.id, ["N9"])
    with pytest.raises(PermissionDeniedError):
        services.shipments.split_shipment(client_actor, first.id, ["N3"])


def test_delivered_status(db, services, admin):
    first = _ship(services, admin)
    part = services.shipments.split_shipment(admin, first.id, ["N3"])
    db.run_transaction(lambda tx: tx.update("orders", "N3", {"status": "delivered"}))

    shipments = [db_ship(services, first.id), db_ship(services, part.id)]
    assert services.shipments.delivered_ids(shipments) == {part.id}


def db_ship(services, shipment_id):
    return services.shipments.get_shipment(None, shipment_id)[0]

"""«💰 Баланс» / «📦 Получил посылку» in the client's chat (the owner, 26.10.2026)."""

import io
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from conftest import START_BALANCE, balance, seed_order
from PIL import Image

from crm.bot.handlers.client_buttons import (
    ALL,
    DONE,
    TOGGLE,
    admin_report,
    checklist,
)
from crm.domain.errors import PermissionDeniedError
from crm.services.common import Actor
from crm.services.share_pictures import balance_picture, shipment_picture, since_last_deposit

pytestmark = pytest.mark.usefixtures("client_doc")


def _shipment(db, services, admin):
    for n in (1, 2, 3):
        seed_order(db, f"N{n}", status="warehouse", brand="Nike", model=f"Model {n}", size="270")
    return services.shipments.ship_orders(admin, ["N1", "N2", "N3"], "AV7414").shipment


def test_everything_arrived(db, services, admin, client_actor):
    shipment = _shipment(db, services, admin)

    result = services.orders.client_received(client_actor, shipment.id, ["N1", "N2", "N3"])

    assert result.delivered == ["N1", "N2", "N3"] and result.missing == []
    assert all(db.get("orders", f"N{n}")["status"] == "delivered" for n in (1, 2, 3))
    assert services.shipments.delivered_ids([db_shipment(services, shipment.id)]) == {shipment.id}
    assert balance(db) == START_BALANCE  # no money moves


def test_part_arrived_the_rest_needs_attention(db, services, admin, client_actor):
    shipment = _shipment(db, services, admin)

    result = services.orders.client_received(client_actor, shipment.id, ["n1", "N3"])

    assert result.delivered == ["N1", "N3"] and result.missing == ["N2"]
    missing = db.get("orders", "N2")
    assert missing["status"] == "cargo" and missing["attention_required"] is True
    assert db.get("orders", "N1").get("attention_required") in (None, False)
    assert services.shipments.delivered_ids([db_shipment(services, shipment.id)]) == set()
    # Later the last pair arrives: the shipment is delivered.
    again = services.orders.client_received(client_actor, shipment.id, ["N2"])
    assert again.delivered == ["N2"] and again.missing == []
    assert balance(db) == START_BALANCE


def test_only_admin_or_client(db, services, admin):
    shipment = _shipment(db, services, admin)
    stranger = Actor.telegram(555, None)
    with pytest.raises(PermissionDeniedError):
        services.orders.client_received(stranger, shipment.id, ["N1"])


def db_shipment(services, shipment_id):
    found, _ = services.shipments.get_shipment(services_admin(), shipment_id)
    return found


def services_admin():
    from crm.domain.enums import Role

    return Actor.telegram(1, Role.ADMIN)


def test_checklist_keeps_ticks_in_the_callback_data(db, services, admin):
    shipment = _shipment(db, services, admin)
    _, orders = services.shipments.get_shipment(admin, shipment.id)

    markup = checklist(shipment, orders, 0b101)
    rows = markup.inline_keyboard
    assert [r[0].text[:1] for r in rows[:3]] == ["☑", "☐", "☑"]
    assert rows[1][0].callback_data == f"{TOGGLE}{shipment.id}:5:1"
    assert rows[3][0].callback_data == f"{ALL}{shipment.id}"
    assert (
        rows[3][1].text == "📥 Получено (2)"
        and rows[3][1].callback_data == f"{DONE}{shipment.id}:5"
    )
    big = checklist(shipment, orders * 20, (1 << 60) - 1)
    assert all(len(b.callback_data.encode()) <= 64 for row in big.inline_keyboard for b in row)

    text = admin_report(shipment, orders, ["N1", "N3"], ["N2"])
    assert (
        "Клиент получил не всё" in text and "❌ <b>N2 · Nike Model 2 · 270 — не пришёл</b>" in text
    )


def test_pictures_are_drawn(db, services, admin):
    shipment = _shipment(db, services, admin)
    _, orders = services.shipments.get_shipment(admin, shipment.id)

    png = shipment_picture(shipment, orders, lambda url: None)
    image = Image.open(io.BytesIO(png))
    assert image.format == "PNG" and image.width == 1080 and image.height > 500

    rows = [
        {
            "type": "order_charge",
            "order_id": "N1",
            "amount_krw": -159000,
            "order": {"title": "Nike Air Max 90"},
        },
        {"type": "deposit", "order_id": None, "amount_krw": 1000000},
        {"type": "adjustment", "order_id": None, "amount_krw": -5000},
    ]
    assert since_last_deposit(rows) == rows[:2]
    png = balance_picture(
        841000,
        Decimal(1350),
        Decimal("622.96"),
        rows[:2],
        lambda url: None,
        datetime(2026, 10, 26, tzinfo=UTC),
    )
    assert Image.open(io.BytesIO(png)).height == 48 + 310 + 60 + 2 * 124 + 48


def test_only_the_parcel_button_is_shown_for_now():
    from crm.bot.handlers.client_buttons import CLIENT_KEYBOARD, PARCEL_BUTTON

    assert [[b.text for b in row] for row in CLIENT_KEYBOARD.keyboard] == [[PARCEL_BUTTON]]

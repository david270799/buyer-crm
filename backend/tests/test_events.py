"""Events: order history and the notifications bell."""

from datetime import timedelta
from decimal import Decimal

import pytest
from conftest import seed, seed_order

from crm.domain.enums import OrderStatus
from crm.domain.errors import ConflictError
from crm.services.order_service import BulkUpdate, NewOrder, OrderUpdate
from crm.services.shipment_service import ShipmentDetails, ShipmentUpdate

pytestmark = pytest.mark.usefixtures("client_doc")


def events(db):
    rows = [data for _, data in db.query("events")]
    return sorted(rows, key=lambda e: e["created_at"])


def types(db):
    return [e["type"] for e in events(db)]


def test_buy_and_cancel_are_recorded(db, services, admin):
    seed_order(db, "n5", brand="Nike", model="Dunk", size="270")

    services.orders.buy(admin, "5", 140_000, 170_000)
    services.orders.cancel(admin, "5")

    bought, cancelled = events(db)
    assert bought["type"] == "order_bought" and bought["important"] is False
    assert bought["order_ids"] == ["n5"] and bought["amount_krw"] == -170_000
    assert "Nike Dunk" in bought["body"] and "170,000" in bought["body"]
    assert cancelled["type"] == "order_cancelled" and cancelled["important"] is True
    assert cancelled["amount_krw"] == 170_000 and "Возврат" in cancelled["body"]


def test_events_never_contain_purchase_price_or_internal_comment(db, services, admin):
    seed_order(db, "n5", brand="Nike", internal_comment="секрет")
    services.orders.buy(admin, "5", 123_456, 170_000)
    services.orders.update_details(admin, "5", OrderUpdate(internal_comment="продавец молчит"))
    services.orders.rebuy(admin, "5", 111_111, 180_000, reason="Нет в наличии")

    text = repr(events(db))
    for secret in ("123,456", "123456", "111,111", "111111", "секрет", "продавец"):
        assert secret not in text


def test_failed_operation_records_no_event(db, services, admin):
    seed_order(db, "n5", status="cancelled")
    with pytest.raises(ConflictError):
        services.orders.buy(admin, "5", 1, 2)
    assert events(db) == []


def test_create_and_bulk_status(db, services, admin):
    created = services.orders.create_order(admin, NewOrder(brand="Adidas", model="Samba"))
    for order_id in ("n7", "n8"):
        seed_order(db, order_id, status="bought", client_price=1, charged_amount_krw=1)

    services.orders.set_status(admin, ["7", "8", "9"], OrderStatus.WAREHOUSE)
    services.orders.set_status(admin, ["7", "8"], OrderStatus.WAREHOUSE)  # nothing changes

    first, warehouse = events(db)
    assert first["type"] == "order_created" and first["order_ids"] == [created.id]
    assert warehouse["type"] == "order_warehouse" and warehouse["order_ids"] == ["n7", "n8"]
    assert warehouse["title"] == "Прибыл на склад: n7, n8"


def test_comments_and_attention(db, services, admin):
    seed_order(db, "n5")
    seed_order(db, "n6")

    services.orders.update_details(admin, "5", OrderUpdate(brand="Nike", size="270"))  # no news
    services.orders.update_details(admin, "5", OrderUpdate(client_comment="Задержка 2 дня"))
    services.orders.update_details(admin, "5", OrderUpdate(client_comment="Задержка 2 дня"))
    services.orders.bulk_update(
        admin, ["5", "6"], BulkUpdate(attention_required=True, client_comment="Нужен ответ")
    )

    comment, attention = events(db)
    assert comment["type"] == "comment" and comment["body"] == "Задержка 2 дня"
    assert comment["important"] is False
    assert attention["type"] == "attention" and attention["important"] is True
    assert attention["order_ids"] == ["n5", "n6"] and attention["body"] == "Нужен ответ"


def test_shipment_events(db, services, admin):
    for order_id in ("n1", "n2"):
        seed_order(db, order_id, status="warehouse", client_price=1, charged_amount_krw=1)

    shipment = services.shipments.ship_orders(
        admin, ["1", "2"], "TRK1", ShipmentDetails(shipping_cost_krw=50_000)
    ).shipment
    services.shipments.ship_orders(admin, ["1", "2"], "TRK1")  # repeat: no news
    services.shipments.update_shipment(admin, shipment.id, ShipmentUpdate(shipping_cost_krw=50_000))
    services.shipments.update_shipment(admin, shipment.id, ShipmentUpdate(shipping_cost_krw=60_000))
    services.shipments.update_shipment(
        admin, shipment.id, ShipmentUpdate(tracking_code="TRK2", box_number="B-9")
    )

    sent, cost, updated = events(db)
    assert sent["type"] == "shipment_sent" and sent["important"] is True
    assert sent["shipment_id"] == shipment.id and sent["order_ids"] == ["n1", "n2"]
    assert "TRK1" in sent["body"] and "50,000" in sent["body"]
    assert sent["amount_krw"] == -50_000
    assert cost["type"] == "shipping_cost" and cost["amount_krw"] == -10_000
    assert updated["type"] == "shipment_updated" and "TRK2" in updated["body"]


def test_finance_events(db, services, admin):
    services.finance.deposit(admin, 1_000_000, "Перевод")
    services.finance.adjust(admin, -5_000, "Комиссия")
    services.finance.set_rate(admin, Decimal("1350"))
    assert types(db) == ["deposit", "adjustment", "rate"]
    assert [e["important"] for e in events(db)] == [False, True, False]


def test_rebuy_event_is_important_and_explains_the_price(db, services, admin):
    seed_order(db, "n5", brand="Nike")
    services.orders.buy(admin, "5", 140_000, 170_000)
    services.orders.rebuy(admin, "5", 150_000, 185_000, reason="Магазин отменил заказ")

    rebought = events(db)[-1]
    assert rebought["type"] == "order_rebought" and rebought["important"] is True
    assert "Магазин отменил заказ" in rebought["body"]
    assert "170,000 → ₩ 185,000" in rebought["body"]
    assert rebought["amount_krw"] == -15_000


def test_feed_filters_and_pages(db, services, admin, client_actor):
    for i in range(1, 8):
        seed_order(db, f"n{i}")
        services.orders.buy(admin, str(i), 1, 10)  # normal
        services.orders.cancel(admin, str(i))  # important

    everything = services.events.feed(client_actor, limit=10)
    important = services.events.feed(client_actor, important_only=True, limit=5)
    older = services.events.feed(client_actor, limit=10, before=everything[-1].created_at)

    assert len(everything) == 10 and len(older) == 4
    assert {e.id for e in everything}.isdisjoint(e.id for e in older)
    assert all(e.important for e in important) and len(important) == 5
    stamps = [e.created_at for e in everything + older]
    assert stamps == sorted(stamps, reverse=True) and len(set(stamps)) == 14


def test_order_history(db, services, admin, client_actor):
    seed_order(db, "n5")
    seed_order(db, "n6")
    services.orders.buy(admin, "5", 1, 10)
    services.orders.buy(admin, "6", 1, 10)
    services.orders.update_details(admin, "5", OrderUpdate(client_comment="ок"))

    history = services.events.for_order(client_actor, "5")
    assert [e.type.value for e in history] == ["comment", "order_bought"]


def test_unread_counts_per_user(db, services, admin, client_actor, clock):
    seed_order(db, "n5")
    services.orders.buy(admin, "5", 1, 10)
    services.orders.cancel(admin, "5")

    assert services.events.unread(client_actor).total == 2
    assert services.events.unread(client_actor).important == 1

    clock.current += timedelta(minutes=1)
    services.events.mark_read(client_actor)
    assert services.events.unread(client_actor).total == 0
    assert services.events.unread(admin).total == 2  # admin's state is separate

    clock.current += timedelta(minutes=1)
    services.finance.deposit(admin, 100)
    assert services.events.unread(client_actor).total == 1
    assert services.events.unread(client_actor).important == 0


def test_seeded_event_without_type_is_tolerated(db, services, client_actor, clock):
    seed(db, "events", "x", {"title": "Старое", "created_at": clock.now()})
    (event,) = services.events.feed(client_actor)
    assert event.type is None and event.title == "Старое" and not event.important

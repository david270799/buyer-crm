import pytest
from conftest import START_BALANCE, audit_actions, balance, ledger_entries, seed, seed_order

from crm.domain.enums import OrderStatus
from crm.domain.errors import (
    ConfigurationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from crm.services.order_service import NewOrder

pytestmark = pytest.mark.usefixtures("client_doc")


# --- /buy ------------------------------------------------------------------


def test_buy_charges_client_price_once_and_records_history(db, services, admin):
    seed_order(db, "n5")

    result = services.orders.buy(admin, "5", 140_000, 170_000)

    assert not result.already_done
    assert result.change.balance_before == START_BALANCE
    assert result.change.balance_after == START_BALANCE - 170_000
    order = db.get("orders", "n5")
    assert order["status"] == "bought"
    assert order["purchase_price"] == 140_000
    assert order["client_price"] == 170_000
    assert order["profit"] == 30_000
    assert order["charged_amount_krw"] == 170_000
    assert order["bought_at"] is not None
    assert balance(db) == START_BALANCE - 170_000

    entries = ledger_entries(db)
    assert list(entries) == ["order_charge_n5"]
    entry = entries["order_charge_n5"]
    assert entry["type"] == "order_charge"
    assert entry["amount_krw"] == -170_000
    assert entry["balance_before"] == START_BALANCE
    assert entry["balance_after"] == START_BALANCE - 170_000
    assert entry["order_id"] == "n5"
    assert entry["created_by"] == admin.id
    assert audit_actions(db) == ["order.buy"]


def test_repeated_buy_with_same_prices_does_not_charge_again(db, services, admin):
    seed_order(db, "n5")
    services.orders.buy(admin, "n5", 140_000, 170_000)

    again = services.orders.buy(admin, "5", 140_000, 170_000)

    assert again.already_done
    assert balance(db) == START_BALANCE - 170_000
    assert len(ledger_entries(db)) == 1


def test_repeated_buy_with_other_prices_is_refused(db, services, admin):
    seed_order(db, "n5")
    services.orders.buy(admin, "n5", 140_000, 170_000)

    with pytest.raises(ConflictError, match="уже выкуплен"):
        services.orders.buy(admin, "n5", 140_000, 190_000)

    assert balance(db) == START_BALANCE - 170_000
    assert db.get("orders", "n5")["client_price"] == 170_000


def test_negative_balance_is_allowed(db, services, admin):
    seed(db, "client_info", "main_client", {"telegram_id": 1, "balance": 100_000})
    seed_order(db, "n1")

    services.orders.buy(admin, "1", 150_000, 170_000)

    assert balance(db) == -70_000


def test_buy_missing_order(db, services, admin):
    with pytest.raises(NotFoundError, match="n404"):
        services.orders.buy(admin, "404", 1, 1)


def test_buy_cancelled_order_is_refused(db, services, admin):
    seed_order(db, "n7", status="cancelled")
    with pytest.raises(ConflictError, match="отменён"):
        services.orders.buy(admin, "7", 1, 1)
    assert balance(db) == START_BALANCE


def test_buy_unknown_status_is_refused(db, services, admin):
    seed_order(db, "n8", status="в пути")
    with pytest.raises(ConflictError, match="неизвестный статус"):
        services.orders.buy(admin, "8", 1, 1)


def test_bought_order_without_recorded_charge_is_never_charged(db, services, admin):
    # E.g. typed in the Firebase console: status says bought, no charge recorded.
    seed_order(db, "n3", status="bought", purchase_price=100_000, client_price=120_000)

    with pytest.raises(ConflictError, match="не зафиксировано"):
        services.orders.buy(admin, "3", 100_000, 120_000)
    assert balance(db) == START_BALANCE
    assert ledger_entries(db) == {}


def test_status_with_capitals_is_understood(db, services, admin):
    seed_order(
        db,
        "n4",
        status="Bought",
        client_price=50_000,
        purchase_price=40_000,
        charged_amount_krw=50_000,
    )
    assert services.orders.buy(admin, "4", 40_000, 50_000).already_done


def test_buy_bought_status_without_recorded_charge_is_refused(db, services, admin):
    seed_order(db, "n9", status="warehouse", client_price=None, purchase_price=None)
    with pytest.raises(ConflictError, match="не зафиксировано"):
        services.orders.buy(admin, "9", 1, 1)


def test_buy_requires_admin(db, services, client_actor):
    seed_order(db, "n5")
    with pytest.raises(PermissionDeniedError):
        services.orders.buy(client_actor, "5", 1, 2)
    assert db.get("orders", "n5")["status"] == "new"


@pytest.mark.parametrize("purchase, client", [(100, 0), (-1, 10), (10, -5)])
def test_buy_validates_prices(db, services, admin, purchase, client):
    seed_order(db, "n5")
    with pytest.raises(ValidationError):
        services.orders.buy(admin, "5", purchase, client)


def test_buy_negative_profit_is_allowed(db, services, admin):
    seed_order(db, "n5")
    result = services.orders.buy(admin, "5", 200_000, 170_000)
    assert result.order.profit == -30_000


def test_buy_without_client_document_changes_nothing(db, services, admin):
    db.run_transaction(lambda tx: tx.set("client_info", "main_client", {"telegram_id": 1}))
    seed_order(db, "n5")

    with pytest.raises(ConfigurationError, match="balance"):
        services.orders.buy(admin, "5", 1, 2)

    assert db.get("orders", "n5")["status"] == "new"
    assert ledger_entries(db) == {}


def test_existing_charge_entry_blocks_second_charge_atomically(db, services, admin):
    # Someone reset the order to "new" by hand after it had been charged.
    seed_order(db, "n5")
    seed(db, "transactions", "order_charge_n5", {"type": "order_charge", "amount_krw": -1})

    with pytest.raises(ConflictError, match="уже есть в истории"):
        services.orders.buy(admin, "5", 140_000, 170_000)

    assert db.get("orders", "n5")["status"] == "new"
    assert balance(db) == START_BALANCE
    assert audit_actions(db) == []


# --- /cancel ---------------------------------------------------------------


def test_cancel_refunds_once(db, services, admin):
    seed_order(db, "n5")
    services.orders.buy(admin, "5", 140_000, 170_000)

    result = services.orders.cancel(admin, "5")
    again = services.orders.cancel(admin, "n5")

    assert result.refunded_krw == 170_000 and not result.already_done
    assert again.already_done and again.refunded_krw == 0
    assert balance(db) == START_BALANCE
    order = db.get("orders", "n5")
    assert order["status"] == "cancelled"
    assert order["charged_amount_krw"] == 0
    assert order["refunded_amount_krw"] == 170_000
    refund = ledger_entries(db)["order_refund_n5"]
    assert refund["type"] == "order_refund"
    assert refund["amount_krw"] == 170_000
    assert refund["balance_after"] == START_BALANCE


def test_cancel_new_order_has_no_refund(db, services, admin):
    seed_order(db, "n5")
    result = services.orders.cancel(admin, "5")
    assert result.refunded_krw == 0
    assert ledger_entries(db) == {}
    assert balance(db) == START_BALANCE


def test_cancel_without_recorded_charge_refunds_nothing(db, services, admin):
    seed_order(db, "n3", status="bought", client_price=120_000, purchase_price=100_000)
    result = services.orders.cancel(admin, "3")
    assert result.refunded_krw == 0
    assert balance(db) == START_BALANCE


def test_cancel_of_cancelled_order_refunds_nothing(db, services, admin):
    seed_order(db, "n3", status="cancelled", client_price=120_000)
    assert services.orders.cancel(admin, "3").already_done
    assert balance(db) == START_BALANCE


@pytest.mark.parametrize("status", ["cargo", "delivered"])
def test_cancel_shipped_order_is_refused(db, services, admin, status):
    seed_order(db, "n5", status=status, client_price=10)
    with pytest.raises(ConflictError, match="не возвращаются"):
        services.orders.cancel(admin, "5")
    assert balance(db) == START_BALANCE


def test_cancel_order_inside_shipment_is_refused(db, services, admin):
    seed_order(db, "n5", status="warehouse", client_price=10, shipment_id="SHP-2026-001")
    with pytest.raises(ConflictError, match="SHP-2026-001"):
        services.orders.cancel(admin, "5")


# --- /status ---------------------------------------------------------------


def test_set_status_reports_every_order(db, services, admin):
    seed_order(db, "n1", status="bought", client_price=10)
    seed_order(db, "n2", status="new")
    seed_order(db, "n4", status="cancelled")
    seed_order(db, "n5", status="warehouse", client_price=10)

    result = services.orders.set_status(
        admin, ["1", "2", "3", "4", "5", "1"], OrderStatus.WAREHOUSE
    )

    assert result.updated == ["n1"]
    assert result.unchanged == ["n5"]
    assert result.not_found == ["n3"]
    assert [order_id for order_id, _ in result.skipped] == ["n2", "n4"]
    order = db.get("orders", "n1")
    assert order["status"] == "warehouse"
    assert order["warehouse_at"] is not None
    assert audit_actions(db) == ["order.status"]


@pytest.mark.parametrize("status", [OrderStatus.BOUGHT, OrderStatus.CANCELLED, OrderStatus.NEW])
def test_set_status_refuses_money_moving_statuses(db, services, admin, status):
    seed_order(db, "n1", status="bought", client_price=10)
    with pytest.raises(ValidationError):
        services.orders.set_status(admin, ["1"], status)


def test_set_status_cargo_needs_a_shipment(db, services, admin):
    seed_order(db, "n1", status="warehouse", client_price=10)
    seed_order(db, "n2", status="delivered", client_price=10, shipment_id="SHP-2026-001")

    result = services.orders.set_status(admin, ["1", "2"], OrderStatus.CARGO)

    assert result.updated == ["n2"]
    assert result.skipped[0][0] == "n1" and "/cargo" in result.skipped[0][1]


def test_set_status_never_invents_a_charge(db, services, admin):
    seed_order(db, "n3", status="bought", client_price=120_000)

    services.orders.set_status(admin, ["3"], OrderStatus.WAREHOUSE)

    assert "charged_amount_krw" not in db.get("orders", "n3")
    assert services.orders.cancel(admin, "3").refunded_krw == 0
    assert balance(db) == START_BALANCE


def test_set_status_limits_bulk_size(db, services, admin):
    with pytest.raises(ValidationError):
        services.orders.set_status(admin, [str(i) for i in range(1, 102)], OrderStatus.DELIVERED)


# --- create ----------------------------------------------------------------


def test_create_order_continues_numbering_after_existing_orders(db, services, admin):
    for order_id in ("n1", "n2", "n99", "n125"):
        seed_order(db, order_id)

    first = services.orders.create_order(
        admin, NewOrder(brand="Nike", model="Air Max 95", size="270")
    )
    second = services.orders.create_order(admin, NewOrder())

    assert (first.id, second.id) == ("n126", "n127")
    assert db.get("counters", "orders")["next_id"] == 128
    doc = db.get("orders", "n126")
    assert doc["status"] == "new"
    assert doc["charged_amount_krw"] == 0
    assert doc["brand"] == "Nike"
    assert balance(db) == START_BALANCE


def test_create_order_skips_ids_taken_while_counter_was_behind(db, services, admin):
    seed(db, "counters", "orders", {"next_id": 5})
    seed_order(db, "n5")
    seed_order(db, "n6")

    assert services.orders.create_order(admin, NewOrder()).id == "n7"
    assert db.get("counters", "orders")["next_id"] == 8


def test_create_order_in_empty_collection_starts_at_one(db, services, admin):
    assert services.orders.create_order(admin, NewOrder()).id == "n1"


def test_create_order_requires_admin(db, services, client_actor):
    with pytest.raises(PermissionDeniedError):
        services.orders.create_order(client_actor, NewOrder())


def test_get_order_normalises_id(db, services, client_actor):
    seed_order(db, "n12", brand="Adidas")
    assert services.orders.get_order(client_actor, "12").brand == "Adidas"
    with pytest.raises(NotFoundError):
        services.orders.get_order(client_actor, "13")


# --- listing / overview / edits (Mini App) ---------------------------------

from datetime import datetime, timezone  # noqa: E402

from crm.services.order_service import BulkUpdate, OrderQuery, OrderUpdate  # noqa: E402


def _catalog(db):
    seed_order(db, "n1", status="new", brand="Nike", model="Air Max 95", client_price=None)
    seed_order(
        db,
        "n2",
        status="bought",
        brand="Adidas",
        model="Samba",
        client_price=200,
        purchase_price=150,
        profit=50,
        bought_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    seed_order(
        db,
        "n10",
        status="Warehouse",
        brand="Nike",
        model="Dunk",
        client_price=500,
        purchase_price=300,
        profit=200,
        attention_required=True,
        internal_comment="продавец молчит",
        bought_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    seed_order(db, "n3", status="cancelled", brand="Puma", client_price=90)


def test_list_orders_sorts_by_number_and_filters(db, services, admin, client_actor):
    _catalog(db)

    page = services.orders.list_orders(client_actor, OrderQuery())
    assert [o.id for o in page.items] == ["n10", "n3", "n2", "n1"] and page.total == 4

    nike = services.orders.list_orders(client_actor, OrderQuery(search="nike"))
    assert [o.id for o in nike.items] == ["n10", "n1"]
    warehouse = services.orders.list_orders(client_actor, OrderQuery(status=OrderStatus.WAREHOUSE))
    assert [o.id for o in warehouse.items] == ["n10"]  # legacy capitalised status included
    attention = services.orders.list_orders(admin, OrderQuery(attention=True))
    assert [o.id for o in attention.items] == ["n10"]
    oldest = services.orders.list_orders(admin, OrderQuery(sort="oldest", offset=1, limit=2))
    assert [o.id for o in oldest.items] == ["n2", "n3"] and oldest.total == 4
    by_price = services.orders.list_orders(admin, OrderQuery(sort="price_desc"))
    assert by_price.items[0].id == "n10"


def test_internal_comment_is_searchable_only_by_admin(db, services, admin, client_actor):
    _catalog(db)
    assert services.orders.list_orders(admin, OrderQuery(search="молчит")).total == 1
    assert services.orders.list_orders(client_actor, OrderQuery(search="молчит")).total == 0


def test_list_orders_rejects_unknown_sort(db, services, admin):
    with pytest.raises(ValidationError):
        services.orders.list_orders(admin, OrderQuery(sort="random"))


def test_overview_counts_and_profit(db, services, admin, client_actor):
    _catalog(db)

    admin_view = services.orders.overview(admin)
    client_view = services.orders.overview(client_actor)

    assert admin_view.status_counts == {
        "new": 1,
        "bought": 1,
        "warehouse": 1,
        "cargo": 0,
        "delivered": 0,
        "cancelled": 1,
    }
    assert admin_view.attention_count == 1
    assert admin_view.active == 3 and admin_view.total == 4
    assert admin_view.profit_total_krw == 250
    assert admin_view.profit_month_krw == 50  # clock is in September 2026
    assert client_view.profit_total_krw is None and client_view.profit_month_krw is None
    assert [o.id for o in admin_view.recent][:2] == ["n10", "n3"]


def test_update_details_changes_only_given_fields(db, services, admin):
    seed_order(db, "n5", brand="Nike", client_comment="old", legacy_field="keep")

    order = services.orders.update_details(
        admin, "5", OrderUpdate(model="Air Force 1", client_comment=None, attention_required=True)
    )

    doc = db.get("orders", "n5")
    assert doc["brand"] == "Nike" and doc["model"] == "Air Force 1"
    assert doc["client_comment"] is None and doc["attention_required"] is True
    assert doc["legacy_field"] == "keep"
    assert order.model == "Air Force 1" and order.attention_required
    assert "order.update" in audit_actions(db)
    assert balance(db) == START_BALANCE


def test_prices_editable_only_before_buy(db, services, admin):
    seed_order(db, "n5", purchase_price=None, client_price=None)
    services.orders.update_details(admin, "5", OrderUpdate(purchase_price=100, client_price=150))
    assert db.get("orders", "n5")["profit"] == 50

    services.orders.buy(admin, "5", 100, 150)
    with pytest.raises(ConflictError, match="отдельная финансовая операция"):
        services.orders.update_details(admin, "5", OrderUpdate(client_price=999))
    services.orders.update_details(admin, "5", OrderUpdate(client_comment="ок"))  # still fine


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", "ftp://x"])
def test_links_must_be_http(db, services, admin, url):
    seed_order(db, "n5")
    with pytest.raises(ValidationError):
        services.orders.update_details(admin, "5", OrderUpdate(source_url=url))
    with pytest.raises(ValidationError):
        services.orders.create_order(admin, NewOrder(source_url=url))


def test_update_details_needs_changes_and_admin(db, services, admin, client_actor):
    seed_order(db, "n5")
    with pytest.raises(ValidationError):
        services.orders.update_details(admin, "5", OrderUpdate())
    with pytest.raises(PermissionDeniedError):
        services.orders.update_details(client_actor, "5", OrderUpdate(brand="x"))


def test_bulk_update(db, services, admin):
    seed_order(db, "n1")
    seed_order(db, "n2")

    result = services.orders.bulk_update(
        admin, ["1", "2", "3"], BulkUpdate(attention_required=True, client_comment="Задержка")
    )

    assert result.updated == ["n1", "n2"] and result.not_found == ["n3"]
    for order_id in ("n1", "n2"):
        doc = db.get("orders", order_id)
        assert doc["attention_required"] is True and doc["client_comment"] == "Задержка"
    with pytest.raises(ValidationError):
        services.orders.bulk_update(admin, ["1"], BulkUpdate())

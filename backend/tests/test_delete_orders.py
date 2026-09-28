import pytest
from conftest import ADMIN_TG, START_BALANCE, audit_actions, balance, ledger_entries, seed_order

from crm.domain.errors import PermissionDeniedError
from crm.services.container import build_services
from crm.services.order_service import BulkUpdate, NewOrder
from crm.storage.blobs import MemoryBlobStorage

pytestmark = pytest.mark.usefixtures("client_doc")


def _create(services, admin, n: int) -> list[str]:
    return [services.orders.create_order(admin, NewOrder(brand="Nike")).id for _ in range(n)]


def test_delete_new_order_removes_it_everywhere(db, services, admin):
    [order_id] = _create(services, admin, 1)
    assert services.events.for_order(admin, order_id)

    result = services.orders.delete_orders(admin, [order_id])

    assert result.deleted == [order_id]
    assert result.refunds == []
    assert db.get("orders", order_id) is None
    assert services.events.for_order(admin, order_id) == []
    assert balance(db) == START_BALANCE
    assert ledger_entries(db) == {}
    # The audit log keeps the full deleted order.
    assert "order.delete" in audit_actions(db)
    [log] = [d for _, d in db.query("audit_logs") if d["action"] == "order.delete"]
    assert log["before"]["brand"] == "Nike"


def test_numbers_come_back_only_from_the_end(db, services, admin):
    _create(services, admin, 10)

    middle = services.orders.delete_orders(admin, ["1", "2", "3", "4", "5"])
    assert middle.next_order_id == "N11"
    assert _create(services, admin, 1) == ["N11"]

    tail = services.orders.delete_orders(admin, ["9", "10", "11"])
    assert tail.next_order_id == "N9"
    assert _create(services, admin, 2) == ["N9", "N10"]


def test_deleting_everything_starts_from_one(db, services, admin):
    _create(services, admin, 3)

    result = services.orders.delete_orders(admin, ["N1", "N2", "N3"])

    assert result.next_order_id == "N1"
    assert _create(services, admin, 1) == ["N1"]


def test_bought_order_is_refunded_and_its_number_is_not_reused(db, services, admin):
    _create(services, admin, 3)
    services.orders.buy(admin, "N3", 100_000, 120_000)

    result = services.orders.delete_orders(admin, ["N2", "N3"])

    assert result.deleted == ["N2", "N3"]
    assert result.refunds == [("N3", 120_000)]
    assert result.refunded_krw == 120_000
    assert balance(db) == START_BALANCE
    entries = ledger_entries(db)
    # Money history stays: the charge and its refund.
    assert set(entries) == {"order_charge_N3", "order_refund_N3"}
    assert entries["order_refund_N3"]["amount_krw"] == 120_000
    assert "удалён" in entries["order_refund_N3"]["comment"]
    # N2 had no money: it is free again; N3 is not (its ledger IDs are taken).
    assert result.next_order_id == "N4"
    assert _create(services, admin, 1) == ["N4"]
    # Even after deleting N4 the counter stays above N3.
    assert services.orders.delete_orders(admin, ["N4"]).next_order_id == "N4"


def test_cancelled_order_is_deleted_without_a_second_refund(db, services, admin):
    [order_id] = _create(services, admin, 1)
    services.orders.buy(admin, order_id, 100_000, 120_000)
    services.orders.cancel(admin, order_id)

    result = services.orders.delete_orders(admin, [order_id])

    assert result.deleted == [order_id]
    assert result.refunds == []
    assert balance(db) == START_BALANCE


def test_shipped_orders_are_not_deleted(db, services, admin):
    seed_order(db, "N1", status="cargo", shipment_id="SHP-2026-001", charged_amount_krw=50_000)
    seed_order(db, "N2", status="warehouse", shipment_id="SHP-2026-001")
    seed_order(db, "N3")

    result = services.orders.delete_orders(admin, ["N1", "N2", "N3", "N9"])

    assert result.deleted == ["N3"]
    assert [order_id for order_id, _ in result.skipped] == ["N1", "N2"]
    assert result.not_found == ["N9"]
    assert db.get("orders", "N1") is not None
    assert balance(db) == START_BALANCE


def test_preview_matches_what_would_be_deleted(db, services, admin):
    _create(services, admin, 2)
    services.orders.buy(admin, "N2", 100_000, 120_000)
    seed_order(db, "N3", status="delivered", shipment_id="SHP-2026-001")

    preview = services.orders.preview_delete(admin, ["1", "2", "3", "4"])

    assert [o.id for o in preview.orders] == ["N1", "N2"]
    assert preview.refund_krw == 120_000
    assert [order_id for order_id, _ in preview.skipped] == ["N3"]
    assert preview.not_found == ["N4"]
    assert db.get("orders", "N1") is not None  # nothing changed


def test_shared_events_keep_the_other_orders(db, services, admin):
    _create(services, admin, 2)
    services.orders.bulk_update(admin, ["N1", "N2"], BulkUpdate(client_comment="проверить размер"))
    shared = [e for e in services.events.for_order(admin, "N2") if len(e.order_ids) == 2]
    assert shared

    services.orders.delete_orders(admin, ["N1"])

    kept = {e.id: e for e in services.events.for_order(admin, "N2")}
    assert kept[shared[0].id].order_ids == ["N2"]


def test_photos_are_deleted_with_the_order(db, clock, admin):
    blobs = MemoryBlobStorage()
    services = build_services(db, frozenset({ADMIN_TG}), clock, blob_storage=blobs)
    photo = blobs.put("orders/a.webp", b"x", "image/webp")
    thumb = blobs.put("orders/a_thumb.webp", b"x", "image/webp")
    seed_order(db, "N1", photo_url=photo, thumbnail_url=thumb)
    seed_order(db, "N2", photo_url=photo)  # same file on another order: kept

    services.orders.delete_orders(admin, ["N1"])
    assert list(blobs.files) == ["orders/a.webp"]

    services.orders.delete_orders(admin, ["N2"])
    assert blobs.files == {}


def test_intake_link_is_removed_so_the_photo_can_be_added_again(db, services, admin):
    seed_order(db, "N1", source_chat_id=-100, source_message_id=7)
    db.run_transaction(lambda tx: tx.set("intake", "tg-100_7", {"order_id": "N1", "chat_id": -100}))

    services.orders.delete_orders(admin, ["N1"])

    assert db.get("intake", "tg-100_7") is None


def test_only_admin_deletes(db, services, client_actor):
    seed_order(db, "N1")
    with pytest.raises(PermissionDeniedError):
        services.orders.delete_orders(client_actor, ["N1"])
    with pytest.raises(PermissionDeniedError):
        services.orders.preview_delete(client_actor, ["N1"])
    assert db.get("orders", "N1") is not None


def test_several_charged_orders_are_refunded_in_one_go(db, services, admin):
    _create(services, admin, 2)
    services.orders.buy(admin, "N1", 100_000, 120_000)
    services.orders.buy(admin, "N2", 50_000, 70_000)

    result = services.orders.delete_orders(admin, ["N1", "N2"])

    assert result.refunds == [("N1", 120_000), ("N2", 70_000)]
    assert result.change.balance_after == START_BALANCE
    assert balance(db) == START_BALANCE
    assert result.next_order_id == "N3"


def test_client_history_hides_a_deleted_orders_charge_and_refund(db, services, admin, client_actor):
    services.finance.deposit(admin, 500_000, "перевод", "dep1")
    [order_id] = _create(services, admin, 1)
    services.orders.buy(admin, order_id, 100_000, 167_640)
    services.orders.delete_orders(admin, [order_id])

    client_view = services.finance.history(client_actor)
    admin_view = services.finance.history(admin)

    assert [e.type.value for e in client_view] == ["deposit"]
    assert {e.type.value for e in admin_view} == {"deposit", "order_charge", "order_refund"}
    assert client_view[0].balance_after == balance(db)  # the line still adds up

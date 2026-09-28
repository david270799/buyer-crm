"""SQLite file database: durability, single writer, read-only access, backups."""

import sqlite3
from datetime import datetime, timezone

import pytest
from conftest import ADMIN_TG, CLIENT_TG, START_BALANCE, FakeClock

from crm.domain.enums import Role
from crm.services.common import Actor
from crm.services.container import build_services
from crm.services.order_service import NewOrder
from crm.storage import StorageError
from crm.storage.sqlite import SqliteDatabase, backup_to


def _client(db):
    db.run_transaction(
        lambda tx: tx.set(
            "client_info", "main_client", {"telegram_id": CLIENT_TG, "balance": START_BALANCE}
        )
    )


def test_everything_survives_a_restart(tmp_path):
    path = tmp_path / "crm.sqlite3"
    db = SqliteDatabase(path)
    _client(db)
    services = build_services(db, frozenset({ADMIN_TG}), FakeClock())
    admin = Actor.telegram(ADMIN_TG, Role.ADMIN)
    services.orders.create_order(admin, NewOrder(brand="Nike"))
    services.orders.buy(admin, "1", 140_000, 170_000)
    before = {
        c: db.query(c) for c in ("orders", "transactions", "client_info", "events", "counters")
    }
    db.close()

    reopened = SqliteDatabase(path)

    after = {c: reopened.query(c) for c in before}
    assert after == before  # datetimes, ints, lists, nested maps — all the same
    assert reopened.get("orders", "N1")["status"] == "bought"
    assert reopened.get("client_info", "main_client")["balance"] == START_BALANCE - 170_000
    again = build_services(reopened, frozenset({ADMIN_TG}), FakeClock())
    assert again.orders.buy(admin, "1", 140_000, 170_000).already_done  # still charged once
    next_order = again.orders.create_order(admin, NewOrder())
    assert next_order.id == "N2"
    reopened.close()


def test_types_round_trip(tmp_path):
    path = tmp_path / "crm.sqlite3"
    moment = datetime(2026, 9, 27, 3, 4, 5, 123000, tzinfo=timezone.utc)
    doc = {
        "t": moment,
        "n": 5,
        "f": 1.5,
        "b": True,
        "none": None,
        "l": [moment, "x"],
        "m": {"inner": moment, "$dt": "not a date: two keys"},
        "raw": b"\x00\x01",
    }
    db = SqliteDatabase(path)
    db.run_transaction(lambda tx: tx.set("c", "a", doc))
    db.close()
    assert SqliteDatabase(path, read_only=True).get("c", "a") == doc


def test_a_failed_write_changes_nothing(tmp_path, monkeypatch):
    db = SqliteDatabase(tmp_path / "crm.sqlite3")
    db.run_transaction(lambda tx: tx.set("c", "a", {"v": 1}))

    class BrokenConnection:
        in_transaction = False

        def __init__(self, real):
            self.real = real

        def execute(self, sql, *args):
            if sql.startswith("BEGIN"):
                raise sqlite3.OperationalError("disk I/O error")
            return self.real.execute(sql, *args)

    real = db._conn
    db._conn = BrokenConnection(real)
    with pytest.raises(StorageError):
        db.run_transaction(lambda tx: tx.update("c", "a", {"v": 2}))
    db._conn = real

    assert db.get("c", "a") == {"v": 1}  # memory untouched
    db.close()
    assert SqliteDatabase(tmp_path / "crm.sqlite3").get("c", "a") == {"v": 1}


def test_only_one_process_writes(tmp_path):
    path = tmp_path / "crm.sqlite3"
    first = SqliteDatabase(path)
    with pytest.raises(StorageError, match="уже открыта"):
        SqliteDatabase(path)
    reader = SqliteDatabase(path, read_only=True)  # doctor and backups still can read
    with pytest.raises(StorageError):
        reader.run_transaction(lambda tx: tx.set("c", "a", {"v": 1}))
    first.close()
    SqliteDatabase(path).close()  # the lock is released on close


def test_read_only_needs_an_existing_file(tmp_path):
    with pytest.raises(StorageError, match="не найден"):
        SqliteDatabase(tmp_path / "missing.sqlite3", read_only=True)


def test_backup_of_a_live_database_and_sql_views(tmp_path):
    path = tmp_path / "crm.sqlite3"
    db = SqliteDatabase(path)
    _client(db)
    services = build_services(db, frozenset({ADMIN_TG}), FakeClock())
    admin = Actor.telegram(ADMIN_TG, Role.ADMIN)
    services.orders.create_order(admin, NewOrder(brand="Nike", model="Dunk"))
    services.orders.buy(admin, "1", 140_000, 170_000)

    copy = tmp_path / "copy.sqlite3"
    backup_to(path, copy)  # while the server still has it open

    conn = sqlite3.connect(copy)
    order = conn.execute(
        "SELECT order_id, status, brand, client_price, profit FROM orders_v"
    ).fetchone()
    assert order == ("N1", "bought", "Nike", 170_000, 30_000)
    [(kind, amount)] = conn.execute("SELECT type, amount_krw FROM transactions_v").fetchall()
    assert (kind, amount) == ("order_charge", -170_000)
    conn.close()
    db.close()
    assert SqliteDatabase(copy, read_only=True).get("orders", "N1")["brand"] == "Nike"

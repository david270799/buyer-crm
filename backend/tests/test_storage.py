"""Contract tests: the in-memory fake must behave like Firestore.

They run on both backends, so any divergence between the fake and the real
emulator shows up here instead of in production.
"""

from datetime import datetime, timezone

import pytest
from conftest import seed

from crm.storage import (
    DocumentExistsError,
    DocumentMissingError,
    Filter,
    OrderBy,
    ReadAfterWriteError,
)
from crm.storage.memory import InMemoryDatabase


def test_read_after_write_is_rejected(db):
    def fn(tx):
        tx.set("c", "a", {"v": 1})
        tx.get("c", "a")

    with pytest.raises(ReadAfterWriteError):
        db.run_transaction(fn)
    assert db.get("c", "a") is None


def test_failed_create_rolls_back_whole_transaction(db):
    seed(db, "c", "exists", {"v": 1})

    def fn(tx):
        tx.set("c", "other", {"v": 2})
        tx.create("c", "exists", {"v": 3})

    with pytest.raises(DocumentExistsError):
        db.run_transaction(fn)
    assert db.get("c", "other") is None
    assert db.get("c", "exists") == {"v": 1}


def test_update_of_missing_document_fails(db):
    with pytest.raises(DocumentMissingError):
        db.run_transaction(lambda tx: tx.update("c", "missing", {"v": 1}))


def test_update_keeps_other_fields_and_merge_set(db):
    seed(db, "c", "a", {"keep": 1, "v": 1})
    db.run_transaction(lambda tx: tx.update("c", "a", {"v": 2}))
    db.run_transaction(lambda tx: tx.set("c", "a", {"extra": True}, merge=True))
    assert db.get("c", "a") == {"keep": 1, "v": 2, "extra": True}


def test_get_many_reports_missing_documents(db):
    seed(db, "c", "a", {"v": 1})
    assert db.get_many("c", ["a", "b"]) == {"a": {"v": 1}, "b": None}
    assert db.run_transaction(lambda tx: tx.get_many("c", ["b", "a"])) == {
        "b": None,
        "a": {"v": 1},
    }


def test_query_filters_order_and_limit(db):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    seed(db, "c", "a", {"k": "x", "n": 3, "t": t0})
    seed(db, "c", "b", {"k": "x", "n": 1})
    seed(db, "c", "c", {"k": "y", "n": 2})

    assert [i for i, _ in db.query("c", [Filter("k", "==", "x")])] == ["a", "b"]
    assert [i for i, _ in db.query("c", order_by=OrderBy("n", descending=True), limit=2)] == [
        "a",
        "c",
    ]
    # Documents without the ordered field are excluded, as in Firestore.
    assert [i for i, _ in db.query("c", order_by=OrderBy("t"))] == ["a"]
    assert sorted(db.list_ids("c")) == ["a", "b", "c"]


def test_datetimes_round_trip(db):
    moment = datetime(2026, 9, 27, 3, 4, 5, 123000, tzinfo=timezone.utc)
    seed(db, "c", "a", {"t": moment})
    assert db.get("c", "a")["t"] == moment


def test_memory_rejects_types_firestore_cannot_store():
    from decimal import Decimal

    db = InMemoryDatabase()
    with pytest.raises(TypeError):
        db.run_transaction(lambda tx: tx.set("c", "a", {"v": Decimal("1")}))


def test_memory_transaction_retries_when_reads_go_stale():
    db = InMemoryDatabase()
    seed(db, "c", "doc", {"value": 1})
    attempts = []

    def fn(tx):
        value = tx.get("c", "doc")["value"]
        attempts.append(value)
        if len(attempts) == 1:
            # A concurrent writer commits between our read and our commit.
            db.run_transaction(lambda other: other.update("c", "doc", {"value": 10}))
        tx.update("c", "doc", {"value": value + 1})

    db.run_transaction(fn)

    assert attempts == [1, 10]
    assert db.get("c", "doc")["value"] == 11


def test_firestore_scan_cache_is_dropped_by_our_writes_and_expires():
    import os
    import time
    import uuid

    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        pytest.skip("FIRESTORE_EMULATOR_HOST is not set")
    from google.cloud.firestore_v1 import Client

    from crm.storage.firestore import FirestoreDatabase

    client = Client(project=f"demo-cache-{uuid.uuid4().hex[:10]}")
    db = FirestoreDatabase(client, scan_cache_seconds=0.5, cached_collections=("orders",))
    db.run_transaction(lambda tx: tx.set("orders", "N1", {"v": 1}))
    assert [i for i, _ in db.scan("orders")] == ["N1"]

    client.collection("orders").document("N2").set({"v": 2})  # written outside the CRM
    assert [i for i, _ in db.scan("orders")] == ["N1"]  # served from cache

    db.run_transaction(lambda tx: tx.update("orders", "N1", {"v": 10}))  # our write
    rows = dict(db.scan("orders"))
    assert rows["N1"] == {"v": 10} and "N2" in rows

    client.collection("orders").document("N3").set({"v": 3})
    time.sleep(0.6)
    assert sorted(dict(db.scan("orders"))) == ["N1", "N2", "N3"]  # expired, re-read
    assert [i for i, _ in db.scan("shipments")] == []  # uncached collections read directly


def test_after_commit_runs_once_and_only_on_success(db):
    seed(db, "c", "exists", {"v": 1})
    calls = []

    def ok(tx):
        tx.get("c", "exists")
        tx.set("c", "a", {"v": 1})
        tx.after_commit(lambda: calls.append(db.get("c", "a")))  # sees the committed data

    db.run_transaction(ok)
    assert calls == [{"v": 1}]

    def fails(tx):
        tx.after_commit(lambda: calls.append("must not run"))
        tx.create("c", "exists", {"v": 2})

    with pytest.raises(DocumentExistsError):
        db.run_transaction(fails)
    assert calls == [{"v": 1}]


def test_after_commit_error_does_not_undo_the_commit(db):
    def fn(tx):
        tx.set("c", "a", {"v": 1})
        tx.after_commit(lambda: 1 / 0)

    db.run_transaction(fn)
    assert db.get("c", "a") == {"v": 1}


def test_memory_after_commit_ignores_retried_attempts():
    db = InMemoryDatabase()
    seed(db, "c", "doc", {"value": 1})
    calls = []

    def fn(tx):
        value = tx.get("c", "doc")["value"]
        if not calls and value == 1:
            db.run_transaction(lambda other: other.update("c", "doc", {"value": 10}))
        tx.update("c", "doc", {"value": value + 1})
        tx.after_commit(lambda: calls.append(value))

    db.run_transaction(fn)
    assert calls == [10]

"""Money must move exactly once even when the same command runs in parallel.

Money invariants are asserted strictly on every backend. Liveness (every
parallel call succeeds) is asserted on the in-memory backend only: under
six truly simultaneous writers the Firestore emulator may still give up on
a caller with TransactionContentionError after all retries. That caller is
told to repeat the command, and nothing was written for it.
"""

import threading

import pytest
from conftest import START_BALANCE, balance, ledger_entries, seed_order

from crm.services.order_service import NewOrder
from crm.storage import TransactionContentionError
from crm.storage.memory import InMemoryDatabase

pytestmark = pytest.mark.usefixtures("client_doc")

WORKERS = 6


def _run_parallel(fn, workers=WORKERS):
    barrier = threading.Barrier(workers)
    results, errors = [], []

    def worker():
        barrier.wait()
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001 - collected for assertions
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    return results, errors


def _check_errors(db, errors):
    if isinstance(db, InMemoryDatabase):
        assert errors == []
    else:
        assert all(isinstance(e, TransactionContentionError) for e in errors), errors


def test_parallel_buy_charges_once(db, services, admin):
    seed_order(db, "n5")

    results, errors = _run_parallel(lambda: services.orders.buy(admin, "5", 140_000, 170_000))

    _check_errors(db, errors)
    charges = [key for key in ledger_entries(db) if key.startswith("order_charge")]
    assert charges == ["order_charge_n5"]
    assert sum(not r.already_done for r in results) <= 1
    assert balance(db) == START_BALANCE - 170_000


def test_parallel_cancel_refunds_once(db, services, admin):
    seed_order(db, "n5")
    services.orders.buy(admin, "5", 140_000, 170_000)

    results, errors = _run_parallel(lambda: services.orders.cancel(admin, "5"))

    _check_errors(db, errors)
    refunds = [key for key in ledger_entries(db) if key.startswith("order_refund")]
    assert refunds == ["order_refund_n5"]
    assert sum(r.refunded_krw for r in results) <= 170_000
    assert balance(db) == START_BALANCE


def test_parallel_order_creation_never_duplicates_ids(db, services, admin):
    seed_order(db, "n125")

    results, errors = _run_parallel(lambda: services.orders.create_order(admin, NewOrder()))

    _check_errors(db, errors)
    ids = [order.id for order in results]
    assert len(ids) == len(set(ids)) == WORKERS - len(errors)
    stored = sorted(i for i in db.list_ids("orders") if i != "n125")
    assert stored == sorted(ids)
    assert db.get("counters", "orders")["next_id"] > max(int(i[1:]) for i in ids)


def test_parallel_deposits_on_different_keys_all_apply(db, services, admin):
    counter = iter(range(WORKERS))
    lock = threading.Lock()

    def deposit():
        with lock:
            key = f"k{next(counter)}"
        return services.finance.deposit(admin, 1_000, idempotency_key=key)

    results, errors = _run_parallel(deposit)

    _check_errors(db, errors)
    assert len(ledger_entries(db)) == len(results)
    assert balance(db) == START_BALANCE + len(results) * 1_000

"""Money must move exactly once even when the same command runs in parallel."""

import threading

import pytest
from conftest import START_BALANCE, balance, ledger_entries, seed_order

from crm.services.order_service import NewOrder

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
        thread.join(timeout=60)
    return results, errors


def test_parallel_buy_charges_once(db, services, admin):
    seed_order(db, "n5")

    results, errors = _run_parallel(lambda: services.orders.buy(admin, "5", 140_000, 170_000))

    assert errors == []
    assert sum(not r.already_done for r in results) == 1
    assert balance(db) == START_BALANCE - 170_000
    assert list(ledger_entries(db)) == ["order_charge_n5"]


def test_parallel_cancel_refunds_once(db, services, admin):
    seed_order(db, "n5")
    services.orders.buy(admin, "5", 140_000, 170_000)

    results, errors = _run_parallel(lambda: services.orders.cancel(admin, "5"))

    assert errors == []
    assert sum(r.refunded_krw for r in results) == 170_000
    assert balance(db) == START_BALANCE


def test_parallel_order_creation_never_duplicates_ids(db, services, admin):
    seed_order(db, "n125")

    results, errors = _run_parallel(lambda: services.orders.create_order(admin, NewOrder()))

    assert errors == []
    ids = sorted(order.id for order in results)
    assert ids == [f"n{126 + i}" for i in range(WORKERS)]


def test_parallel_deposits_on_different_keys_all_apply(db, services, admin):
    counter = iter(range(WORKERS))
    lock = threading.Lock()

    def deposit():
        with lock:
            key = f"k{next(counter)}"
        return services.finance.deposit(admin, 1_000, idempotency_key=key)

    results, errors = _run_parallel(deposit)

    assert errors == []
    assert balance(db) == START_BALANCE + WORKERS * 1_000

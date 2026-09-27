"""Shared fixtures.

Every test that takes `db` runs twice: against the in-memory database and,
when FIRESTORE_EMULATOR_HOST is set, against the real Firestore emulator
(each test in its own throw-away project, so tests never share data).
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from crm.domain.enums import Role
from crm.services.common import Actor
from crm.services.container import Services, build_services
from crm.storage import Database
from crm.storage.memory import InMemoryDatabase

ADMIN_TG = 1001
CLIENT_TG = 2002
START_BALANCE = 1_000_000


class FakeClock:
    """Deterministic UTC clock; every call moves one second forward."""

    def __init__(self, start: datetime = datetime(2026, 9, 27, 3, 0, tzinfo=timezone.utc)):
        self.current = start

    def now(self) -> datetime:
        self.current += timedelta(seconds=1)
        return self.current


def _emulator_database() -> Database:
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        pytest.skip("FIRESTORE_EMULATOR_HOST is not set")
    from google.cloud.firestore_v1 import Client

    from crm.storage.firestore import FirestoreDatabase

    return FirestoreDatabase(Client(project=f"demo-crm-{uuid.uuid4().hex[:12]}"))


@pytest.fixture(params=["memory", pytest.param("emulator", marks=pytest.mark.emulator)])
def db(request) -> Database:
    if request.param == "memory":
        return InMemoryDatabase()
    return _emulator_database()


def seed(db: Database, collection: str, doc_id: str, data: dict) -> None:
    db.run_transaction(lambda tx: tx.set(collection, doc_id, data))


def seed_order(db: Database, order_id: str, **fields) -> None:
    data = {
        "order_id": order_id,
        "status": "new",
        "purchase_price": 0,
        "client_price": 0,
        "profit": 0,
        "cargo_code": None,
    }
    data.update(fields)
    seed(db, "orders", order_id, data)


def balance(db: Database) -> int:
    return db.get("client_info", "main_client")["balance"]


def ledger_entries(db: Database) -> dict[str, dict]:
    return dict(db.query("transactions"))


def audit_actions(db: Database) -> list[str]:
    return sorted(data["action"] for _, data in db.query("audit_logs"))


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def services(db: Database, clock: FakeClock) -> Services:
    return build_services(db, frozenset({ADMIN_TG}), clock)


@pytest.fixture
def client_doc(db: Database) -> None:
    seed(
        db,
        "client_info",
        "main_client",
        {"telegram_id": CLIENT_TG, "name": "Client", "balance": START_BALANCE},
    )


@pytest.fixture
def admin() -> Actor:
    return Actor.telegram(ADMIN_TG, Role.ADMIN)


@pytest.fixture
def client_actor() -> Actor:
    return Actor.telegram(CLIENT_TG, Role.CLIENT)

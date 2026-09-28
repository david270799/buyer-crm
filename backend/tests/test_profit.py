"""The admin's extra profit: counted in the admin's profit figures, never shown
to the client and never touching the client's balance."""

import json

import pytest
from conftest import ADMIN_TG, CLIENT_TG, START_BALANCE, balance, ledger_entries, seed_order
from fastapi.testclient import TestClient

from crm.api.app import ApiConfig, create_app
from crm.api.telegram_auth import make_init_data
from crm.domain.errors import ConflictError, PermissionDeniedError, ValidationError
from crm.services.container import build_services

BOT_TOKEN = "123456:TEST-token"
pytestmark = pytest.mark.usefixtures("client_doc")


def test_profit_is_added_to_admin_figures_only(db, services, admin):
    seed_order(
        db,
        "N1",
        status="bought",
        client_price=120,
        purchase_price=100,
        profit=20,
        charged_amount_krw=120,
        bought_at=services.orders._clock.now(),
    )
    before = services.orders.overview(admin)

    result = services.profit.add(admin, 50_000, "  кэшбэк магазина ", "k1")

    assert not result.already_done and result.entry.comment == "кэшбэк магазина"
    after = services.orders.overview(admin)
    assert after.profit_total_krw == before.profit_total_krw + 50_000
    assert after.profit_month_krw == before.profit_month_krw + 50_000
    assert balance(db) == START_BALANCE
    assert ledger_entries(db) == {}
    assert [e.amount_krw for e in services.profit.history(admin)] == [50_000]


def test_profit_is_idempotent_and_validated(db, services, admin, client_actor):
    services.profit.add(admin, 10_000, None, "k1")
    assert services.profit.add(admin, 10_000, None, "k1").already_done
    with pytest.raises(ConflictError):
        services.profit.add(admin, 20_000, None, "k1")
    with pytest.raises(ValidationError):
        services.profit.add(admin, 0)
    services.profit.add(admin, -3_000, "поправка")
    assert sorted(e.amount_krw for e in services.profit.history(admin)) == [-3_000, 10_000]
    with pytest.raises(PermissionDeniedError):
        services.profit.add(client_actor, 1_000)
    with pytest.raises(PermissionDeniedError):
        services.profit.history(client_actor)


def test_client_never_sees_profit_over_http(db, clock):
    services = build_services(db, frozenset({ADMIN_TG}), clock)
    client = TestClient(create_app(services, ApiConfig(bot_token=BOT_TOKEN)))

    def call(method, path, who=ADMIN_TG, **kw):
        headers = {"Authorization": f"tma {make_init_data(who, BOT_TOKEN)}"}
        return client.request(method, path, headers=headers, **kw)

    body = {"amount_krw": 70_000, "comment": "секретный кэшбэк", "idempotency_key": "key-12345"}
    added = call("POST", "/api/finance/profit", json=body).json()
    assert added["entry"]["amount_krw"] == 70_000
    assert call("GET", "/api/finance/profit").json()["items"][0]["comment"] == "секретный кэшбэк"
    assert call("GET", "/api/overview").json()["orders"]["profit_total_krw"] == 70_000

    assert call("POST", "/api/finance/profit", who=CLIENT_TG, json=body).status_code == 403
    assert call("GET", "/api/finance/profit", who=CLIENT_TG).status_code == 403
    for path in ("/api/overview", "/api/transactions", "/api/events"):
        text = json.dumps(call("GET", path, who=CLIENT_TG).json(), ensure_ascii=False)
        assert "секретный" not in text and "70000" not in text and "profit" not in text

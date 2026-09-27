"""HTTP API tests: real FastAPI app, signed Telegram initData, both databases."""

import io
import json
import time

import pytest
from conftest import ADMIN_TG, CLIENT_TG, START_BALANCE, balance, ledger_entries, seed_order
from fastapi.testclient import TestClient
from PIL import Image

from crm.api.app import ApiConfig, create_app
from crm.api.telegram_auth import (
    InitDataError,
    make_init_data,
    sign_init_data,
    validate_init_data,
)
from crm.services.container import build_services
from crm.storage.blobs import MemoryBlobStorage

BOT_TOKEN = "123456:TEST-token"
ADMIN_ONLY_KEYS = {
    "source_url",
    "purchase_price",
    "profit",
    "internal_comment",
    "charged_amount_krw",
    "shipping_charged_krw",
    "created_by",
    "updated_by",
    "source",
    "profit_total_krw",
    "profit_month_krw",
}


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


@pytest.fixture
def blobs():
    return MemoryBlobStorage()


@pytest.fixture
def api(db, clock, client_doc, blobs):
    services = build_services(db, frozenset({ADMIN_TG}), clock, blob_storage=blobs)
    app = create_app(services, ApiConfig(bot_token=BOT_TOKEN))
    client = TestClient(app, raise_server_exceptions=False)

    def call(method: str, path: str, who: int | None = ADMIN_TG, **kwargs):
        headers = kwargs.pop("headers", {})
        if who is not None:
            headers["Authorization"] = f"tma {make_init_data(who, BOT_TOKEN)}"
        return client.request(method, path, headers=headers, **kwargs)

    return call


# --- initData ---------------------------------------------------------------


def test_init_data_roundtrip_and_matches_aiogram():
    from aiogram.utils.web_app import safe_parse_webapp_init_data

    init_data = make_init_data(42, BOT_TOKEN, first_name="Иван")
    user = validate_init_data(init_data, BOT_TOKEN)
    assert user.id == 42 and user.first_name == "Иван"
    # Independent reference implementation accepts the same string.
    assert safe_parse_webapp_init_data(BOT_TOKEN, init_data).user.id == 42


def test_init_data_signed_by_aiogram_style_fields_is_accepted():
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": 7, "first_name": "A"}),
        "chat_instance": "-1",
        "chat_type": "sender",
        "signature": "abc",
    }
    assert validate_init_data(sign_init_data(fields, BOT_TOKEN), BOT_TOKEN).id == 7


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.replace("Test", "Evil"),  # tampered user
        lambda s: s + "&extra=1",  # added field
        lambda s: s.replace("hash=", "hash=0"),  # broken hash
        lambda s: "",
    ],
)
def test_tampered_init_data_is_rejected(mutate):
    with pytest.raises(InitDataError):
        validate_init_data(mutate(make_init_data(1, BOT_TOKEN)), BOT_TOKEN)


def test_init_data_from_other_bot_or_expired_is_rejected():
    with pytest.raises(InitDataError):
        validate_init_data(make_init_data(1, "999:OTHER"), BOT_TOKEN)
    old = sign_init_data(
        {"auth_date": str(int(time.time()) - 2 * 86400), "user": json.dumps({"id": 1})}, BOT_TOKEN
    )
    with pytest.raises(InitDataError, match="expired"):
        validate_init_data(old, BOT_TOKEN)
    no_user = sign_init_data({"auth_date": str(int(time.time()))}, BOT_TOKEN)
    with pytest.raises(InitDataError):
        validate_init_data(no_user, BOT_TOKEN)


# --- access -----------------------------------------------------------------


def test_requests_without_valid_telegram_auth_are_refused(api):
    assert api("GET", "/api/me", who=None).status_code == 401
    bad = api("GET", "/api/me", who=None, headers={"Authorization": "tma user=1&hash=00"})
    assert bad.status_code == 401
    assert bad.json()["error"]["message"].startswith("Сессия недействительна")
    assert (
        api("GET", "/api/me", who=None, headers={"Authorization": "demo admin"}).status_code == 401
    )
    assert api("GET", "/api/me", who=555).status_code == 403  # valid Telegram user, no role


def test_roles(api):
    assert api("GET", "/api/me").json()["role"] == "admin"
    assert api("GET", "/api/me", who=CLIENT_TG).json()["role"] == "client"


def test_client_sees_no_admin_fields_anywhere(db, api):
    seed_order(db, "n5", status="new", brand="Nike", source_url="https://shop-a.kr/1")
    api("POST", "/api/orders/n5/buy", json={"purchase_price": 140_000, "client_price": 170_000})
    rebuy = {
        "purchase_price": 141_000,
        "client_price": 170_000,
        "source_url": "https://shop-b.kr/2",
    }
    api("POST", "/api/orders/n5/rebuy", json={**rebuy, "reason": "Нет в наличии"})
    api("PATCH", "/api/orders/n5", json={"internal_comment": "секрет", "client_comment": "ок"})
    api("POST", "/api/shipments", json={"order_ids": ["5"], "shipping_cost_krw": 50_000})

    responses = [
        api("GET", path, who=CLIENT_TG).json()
        for path in (
            "/api/overview",
            "/api/orders",
            "/api/orders/n5",
            "/api/shipments",
            "/api/shipments/1",
            "/api/transactions",
            "/api/events",
        )
    ]

    leaked = set().union(*(_keys(r) for r in responses)) & ADMIN_ONLY_KEYS
    assert leaked == set()
    assert "секрет" not in json.dumps(responses, ensure_ascii=False)
    assert "140000" not in json.dumps(responses)
    assert "shop-" not in json.dumps(responses)  # product links are the buyer's own
    order = responses[2]["order"]
    assert order["client_price"] == 170_000 and order["client_comment"] == "ок"


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("POST", "/api/orders", {"brand": "x"}),
        ("PATCH", "/api/orders/n5", {"brand": "x"}),
        ("POST", "/api/orders/n5/buy", {"purchase_price": 1, "client_price": 2}),
        ("POST", "/api/orders/n5/cancel", None),
        ("POST", "/api/orders/bulk/status", {"order_ids": ["5"], "status": "warehouse"}),
        ("POST", "/api/orders/bulk/update", {"order_ids": ["5"], "attention_required": True}),
        ("POST", "/api/shipments", {"order_ids": ["5"]}),
        ("PATCH", "/api/shipments/1", {"comment": "x"}),
        ("POST", "/api/finance/deposit", {"amount_krw": 1, "idempotency_key": "abcdefgh"}),
        ("POST", "/api/finance/adjust", {"amount_krw": 1, "idempotency_key": "abcdefgh"}),
        ("PUT", "/api/settings/rate", {"krw_per_usd": 1300}),
        ("PUT", "/api/settings/notifications", {"recipient": "client"}),
        ("GET", "/api/settings", None),
    ],
)
def test_client_cannot_change_anything(db, api, method, path, body):
    seed_order(db, "n5")
    response = api(method, path, who=CLIENT_TG, json=body)
    assert response.status_code == 403
    assert db.get("orders", "n5")["status"] == "new"
    assert balance(db) == START_BALANCE


# --- admin flows ------------------------------------------------------------


def test_buy_twice_charges_once_and_reports_change(db, api):
    seed_order(db, "n5")
    first = api(
        "POST", "/api/orders/5/buy", json={"purchase_price": 140_000, "client_price": 170_000}
    )
    second = api(
        "POST", "/api/orders/5/buy", json={"purchase_price": 140_000, "client_price": 170_000}
    )

    assert first.status_code == 200
    assert first.json()["change"] == {
        "amount_krw": -170_000,
        "balance_before": START_BALANCE,
        "balance_after": START_BALANCE - 170_000,
    }
    assert second.json()["already_done"] is True and second.json()["change"] is None
    assert balance(db) == START_BALANCE - 170_000

    conflict = api("POST", "/api/orders/5/buy", json={"purchase_price": 1, "client_price": 2})
    assert conflict.status_code == 409 and "уже выкуплен" in conflict.json()["error"]["message"]


def test_create_order_with_buy_now_and_cancel(db, api):
    for order_id in ("n1", "n125"):
        seed_order(db, order_id)
    created = api(
        "POST",
        "/api/orders",
        json={
            "brand": "Nike",
            "model": "Dunk",
            "size": "270",
            "purchase_price": 100_000,
            "client_price": 130_000,
            "buy_now": True,
        },
    ).json()
    assert created["order"]["id"] == "n126" and created["order"]["status"] == "bought"
    assert created["change"]["amount_krw"] == -130_000

    cancelled = api("POST", "/api/orders/n126/cancel").json()
    assert cancelled["refunded_krw"] == 130_000
    assert balance(db) == START_BALANCE
    assert api("POST", "/api/orders/n126/cancel").json()["already_done"] is True


def test_buy_now_requires_prices(api):
    response = api("POST", "/api/orders", json={"brand": "x", "buy_now": True})
    assert response.status_code == 422


def test_list_and_bulk_actions(db, api):
    for order_id in ("n1", "n2", "n3"):
        seed_order(db, order_id, status="bought", client_price=10, charged_amount_krw=10)

    status = api(
        "POST", "/api/orders/bulk/status", json={"order_ids": ["1", "2", "9"], "status": "склад"}
    )
    assert status.json()["updated"] == ["n1", "n2"] and status.json()["not_found"] == ["n9"]
    marked = api(
        "POST",
        "/api/orders/bulk/update",
        json={"order_ids": ["n3"], "attention_required": True, "client_comment": "Задержка"},
    )
    assert marked.json()["updated"] == ["n3"]

    listed = api("GET", "/api/orders", params={"status": "warehouse"}).json()
    assert [o["id"] for o in listed["items"]] == ["n2", "n1"] and listed["total"] == 2
    attention = api("GET", "/api/orders", params={"attention": "true"}).json()
    assert [o["id"] for o in attention["items"]] == ["n3"]
    assert attention["items"][0]["status_label"] == "Выкуплен"
    assert api("GET", "/api/orders", params={"status": "бред"}).status_code == 422


def test_shipment_create_and_cost_change(db, api):
    for order_id in ("n5", "n7"):
        seed_order(db, order_id, status="warehouse", client_price=10, charged_amount_krw=10)

    created = api(
        "POST",
        "/api/shipments",
        json={
            "order_ids": ["5", "7", "8"],
            "tracking_code": "trk-1",
            "box_number": "B18",
            "weight_kg": 12.5,
            "shipping_cost_krw": 95_000,
            "shipment_date": "2026-09-12",
            "comment": "Хрупкое",
        },
    ).json()
    shipment = created["shipment"]
    assert (
        created["created"] and created["added"] == ["n5", "n7"] and created["not_found"] == ["n8"]
    )
    assert shipment["tracking_code"] == "TRK-1" and shipment["order_count"] == 2
    assert shipment["shipment_date"].startswith("2026-09-12T00:00:00+09:00") or shipment[
        "shipment_date"
    ].startswith("2026-09-11T15:00:00")
    assert created["change"]["amount_krw"] == -95_000
    assert balance(db) == START_BALANCE - 95_000

    changed = api("PATCH", f"/api/shipments/{shipment['id']}", json={"shipping_cost_krw": 100_000})
    assert changed.json()["change"]["amount_krw"] == -5_000
    same = api("PATCH", "/api/shipments/1", json={"shipping_cost_krw": 100_000})
    assert same.json()["change"] is None
    assert balance(db) == START_BALANCE - 100_000

    detail = api("GET", "/api/shipments/1").json()
    assert [o["id"] for o in detail["orders"]] == ["n5", "n7"]
    order = api("GET", "/api/orders/n5").json()
    assert order["shipment"]["id"] == shipment["id"]


def test_deposit_is_idempotent_per_key(db, api):
    body = {"amount_krw": 500_000, "comment": "Перевод", "idempotency_key": "form-12345678"}
    first = api("POST", "/api/finance/deposit", json=body).json()
    second = api("POST", "/api/finance/deposit", json=body).json()

    assert not first["already_done"] and second["already_done"]
    assert balance(db) == START_BALANCE + 500_000
    assert "deposit_ma-form-12345678" in ledger_entries(db)

    bad_key = api("POST", "/api/finance/deposit", json={**body, "idempotency_key": "x"})
    assert bad_key.status_code == 422


def test_adjust_rate_overview_and_history(db, api):
    seed_order(db, "n5", brand="Nike", model="Dunk", thumbnail_url="https://img/t.webp")
    api("POST", "/api/orders/5/buy", json={"purchase_price": 100, "client_price": 150})
    api(
        "POST",
        "/api/finance/adjust",
        json={"amount_krw": -1_000, "comment": "Комиссия", "idempotency_key": "adj-00000001"},
    )
    assert (
        api("PUT", "/api/settings/rate", json={"krw_per_usd": 1350}).json()["krw_per_usd"] == 1350
    )

    overview = api("GET", "/api/overview").json()
    assert overview["balance"]["krw"] == START_BALANCE - 150 - 1_000
    assert overview["balance"]["usd"] == pytest.approx((START_BALANCE - 1_150) / 1350)
    assert overview["orders"]["status_counts"]["bought"] == 1
    assert overview["orders"]["profit_total_krw"] == 50

    history = api("GET", "/api/transactions", who=CLIENT_TG).json()["items"]
    assert [item["type"] for item in history] == ["adjustment", "order_charge"]
    assert history[1]["order"] == {
        "id": "n5",
        "title": "Nike Dunk",
        "thumbnail_url": "https://img/t.webp",
    }
    assert api("GET", "/api/settings").json()["krw_per_usd"] == 1350


def test_errors_have_readable_messages(db, api):
    missing = api("GET", "/api/orders/404")
    assert missing.status_code == 404
    assert missing.json() == {
        "error": {"code": "NotFoundError", "message": "Заказ n404 не найден."}
    }
    invalid = api("POST", "/api/orders/5/buy", json={"purchase_price": "много"})
    assert invalid.status_code == 422 and "Traceback" not in invalid.text
    bad_link = api("POST", "/api/orders", json={"source_url": "javascript:alert(1)"})
    assert bad_link.status_code == 422


def test_image_upload(api, blobs):
    image = Image.new("RGB", (2000, 1500), (120, 90, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")

    uploaded = api(
        "POST", "/api/images", files={"file": ("photo.jpg", buffer.getvalue(), "image/jpeg")}
    )

    assert uploaded.status_code == 200
    body = uploaded.json()
    assert body["width"] == body["height"] == 1280  # square, like every photo
    assert body["photo_url"].endswith(".webp") and len(blobs.files) == 2
    client = api(
        "POST",
        "/api/images",
        who=CLIENT_TG,
        files={"file": ("p.jpg", buffer.getvalue(), "image/jpeg")},
    )
    assert client.status_code == 403
    junk = api("POST", "/api/images", files={"file": ("x.jpg", b"junk", "image/jpeg")})
    assert junk.status_code == 422


def test_demo_login_only_in_demo_mode(db, clock, client_doc):
    services = build_services(db, frozenset({ADMIN_TG}), clock)
    demo = TestClient(
        create_app(
            services,
            ApiConfig(bot_token=None, demo=True, demo_admin_id=ADMIN_TG, demo_client_id=CLIENT_TG),
        )
    )
    assert demo.get("/api/config").json() == {"demo": True}
    assert demo.get("/api/me", headers={"Authorization": "demo admin"}).json()["role"] == "admin"
    assert demo.get("/api/me", headers={"Authorization": "demo client"}).json()["role"] == "client"


def test_static_frontend_is_served(db, clock, client_doc, tmp_path):
    (tmp_path / "index.html").write_text("<html>CRM</html>")
    media = tmp_path / "media"
    media.mkdir()
    (media / "p.webp").write_bytes(b"RIFF")
    services = build_services(db, frozenset({ADMIN_TG}), clock)
    client = TestClient(
        create_app(services, ApiConfig(bot_token=BOT_TOKEN, static_dir=tmp_path, media_dir=media))
    )
    assert client.get("/media/p.webp").headers["content-type"] == "image/webp"
    page = client.get("/")
    assert page.status_code == 200 and "CRM" in page.text
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me").headers["cache-control"] == "no-store"


def test_rebuy_endpoint_and_history(db, api):
    seed_order(db, "n5", brand="Nike", source_url="https://shop-a.kr/1")
    api("POST", "/api/orders/5/buy", json={"purchase_price": 140_000, "client_price": 170_000})

    rebuy = api(
        "POST",
        "/api/orders/5/rebuy",
        json={
            "purchase_price": 150_000,
            "client_price": 185_000,
            "source_url": "https://shop-b.kr/2",
            "reason": "Магазин отменил заказ",
        },
    ).json()
    assert rebuy["change"]["amount_krw"] == -15_000
    assert rebuy["order"]["source_url"] == "https://shop-b.kr/2"
    assert len(rebuy["order"]["purchases"]) == 2
    assert balance(db) == START_BALANCE - 185_000

    client_view = api("GET", "/api/orders/n5", who=CLIENT_TG).json()
    assert [h["type"] for h in client_view["history"]] == ["order_rebought", "order_bought"]
    assert not {"purchases", "rebuy_count", "source_url"} & set(client_view["order"])
    assert (
        api(
            "POST",
            "/api/orders/5/rebuy",
            who=CLIENT_TG,
            json={"purchase_price": 1, "client_price": 2},
        ).status_code
        == 403
    )


def test_notifications_feed_and_read_state(db, api):
    seed_order(db, "n5")
    api("POST", "/api/orders/5/buy", json={"purchase_price": 1, "client_price": 10})
    api("POST", "/api/orders/5/cancel")

    unread = api("GET", "/api/events/unread", who=CLIENT_TG).json()
    assert (unread["important"], unread["total"], unread["seen_at"]) == (1, 2, None)
    feed = api("GET", "/api/events", who=CLIENT_TG).json()["items"]
    assert [e["type"] for e in feed] == ["order_cancelled", "order_bought"]
    important = api("GET", "/api/events", who=CLIENT_TG, params={"important": "true"}).json()
    assert [e["type"] for e in important["items"]] == ["order_cancelled"]
    older = api("GET", "/api/events", who=CLIENT_TG, params={"before": feed[0]["created_at"]})
    assert [e["type"] for e in older.json()["items"]] == ["order_bought"]

    assert api("POST", "/api/events/read", who=CLIENT_TG).json() == {"ok": True}
    after = api("GET", "/api/events/unread", who=CLIENT_TG).json()
    assert after["total"] == 0 and after["seen_at"] is not None
    assert api("GET", "/api/events/unread").json()["total"] == 2  # admin separate


def test_notification_settings(db, api):
    initial = api("GET", "/api/settings").json()["notifications"]
    assert initial["recipient"] == "off" and initial["level"] == "important"
    assert initial["client_has_telegram"] is True and initial["bot_running"] is False

    updated = api("PUT", "/api/settings/notifications", json={"recipient": "admins"}).json()
    assert updated["recipient"] == "admins" and updated["level"] == "important"
    updated = api("PUT", "/api/settings/notifications", json={"level": "all"}).json()
    assert updated["recipient"] == "admins" and updated["level"] == "all"

    bad = api("PUT", "/api/settings/notifications", json={"recipient": "everyone"})
    assert bad.status_code == 422 and "error" in bad.json()
    assert db.get("settings", "notifications")["recipient"] == "admins"

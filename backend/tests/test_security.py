import pytest
from conftest import CLIENT_TG
from fastapi.testclient import TestClient

from crm.api.app import ApiConfig, create_app
from crm.api.telegram_auth import make_init_data
from crm.domain.errors import ConflictError, PermissionDeniedError, ValidationError
from crm.services.container import build_services

BOT_TOKEN = "123456:TEST-token"
pytestmark = pytest.mark.usefixtures("client_doc")


def test_pin_set_check_and_remove(db, services, admin):
    assert not services.security.pin_set(admin)
    assert services.security.check(admin, "")  # no PIN: always open
    services.security.set_pin(admin, "4821")
    assert services.security.pin_set(admin)
    assert services.security.check(admin, "4821")
    assert not services.security.check(admin, "0000")
    doc = db.get("settings", "security")
    assert "4821" not in str(doc)  # only a hash is stored
    services.security.set_pin(admin, None)
    assert not services.security.pin_set(admin)


def test_pin_rules_and_rights(db, services, admin, client_actor):
    for bad in ("12", "123456789", "12a4"):
        with pytest.raises(ValidationError):
            services.security.set_pin(admin, bad)
    with pytest.raises(PermissionDeniedError):
        services.security.set_pin(client_actor, "1234")


def test_too_many_wrong_pins_pause_checks(db, services, admin):
    services.security.set_pin(admin, "4821")
    for _ in range(5):
        assert not services.security.check(admin, "0000")
    with pytest.raises(ConflictError):
        services.security.check(admin, "4821")


def test_pin_over_http(db, clock):
    from conftest import ADMIN_TG

    services = build_services(db, frozenset({ADMIN_TG}), clock)
    client = TestClient(create_app(services, ApiConfig(bot_token=BOT_TOKEN)))

    def call(method, path, who=ADMIN_TG, **kw):
        headers = {"Authorization": f"tma {make_init_data(who, BOT_TOKEN)}"}
        return client.request(method, path, headers=headers, **kw)

    assert call("GET", "/api/security").json() == {"pin_set": False, "pin_length": 0}
    assert call("PUT", "/api/security/pin", json={"pin": "4821"}).json() == {"pin_set": True}
    assert call("GET", "/api/security").json() == {"pin_set": True, "pin_length": 4}
    assert call("POST", "/api/security/unlock", json={"pin": "4821"}).json() == {"ok": True}
    assert call("POST", "/api/security/unlock", json={"pin": "1111"}).status_code == 422
    assert call("GET", "/api/security", who=CLIENT_TG).status_code == 403

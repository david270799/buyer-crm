import json

import pytest
from conftest import ADMIN_TG, CLIENT_TG

from crm.domain.errors import ConflictError, PermissionDeniedError
from crm.services.container import build_services


@pytest.fixture
def updates(db, clock, tmp_path):
    return build_services(db, frozenset({ADMIN_TG}), clock, update_dir=tmp_path).updates


def test_update_needs_the_server_updater_installed(updates, admin, tmp_path):
    assert updates.status(admin) == {"installed": False, "state": "idle", "requested": False}
    with pytest.raises(ConflictError, match="install-updater"):
        updates.request(admin)
    assert not (tmp_path / "request.json").exists()


def test_update_request_leaves_a_file_for_the_server(db, updates, admin, client_actor, tmp_path):
    (tmp_path / "installed").write_text("2026-10-21")
    with pytest.raises(PermissionDeniedError):
        updates.request(client_actor)
    result = updates.request(admin)
    assert result["requested"] is True
    assert json.loads((tmp_path / "request.json").read_text())["by"] == admin.id
    assert [d["action"] for _, d in db.query("audit_logs")][-1] == "system.update"
    with pytest.raises(ConflictError, match="уже идёт"):
        updates.request(admin)  # one at a time


def test_update_status_shows_the_outcome_and_log_on_failure(updates, admin, tmp_path):
    (tmp_path / "installed").write_text("x")
    status = {"state": "failed", "before": "a1b2c3d", "after": "a1b2c3d", "exit_code": "1"}
    (tmp_path / "status.json").write_text(json.dumps(status))
    (tmp_path / "update.log").write_text("\n".join(f"line {i}" for i in range(100)))
    result = updates.status(admin)
    assert result["state"] == "failed" and result["log"].splitlines()[-1] == "line 99"
    assert len(result["log"].splitlines()) == 40
    with pytest.raises(ConflictError):
        (tmp_path / "status.json").write_text(json.dumps({"state": "running"}))
        updates.request(admin)  # still running
    (tmp_path / "status.json").write_text(json.dumps({"state": "done", "after": "e5f6a7b"}))
    assert updates.request(admin)["requested"] is True


def test_update_api_is_admin_only(db, clock, client_doc, tmp_path):
    from fastapi.testclient import TestClient

    from crm.api.app import ApiConfig, create_app
    from crm.api.telegram_auth import make_init_data

    services = build_services(db, frozenset({ADMIN_TG}), clock, update_dir=tmp_path)
    client = TestClient(create_app(services, ApiConfig(bot_token="1:x")))

    def call(method, who, **headers):
        auth = {"Authorization": f"tma {make_init_data(who, '1:x')}", **headers}
        return client.request(method, "/api/system/update", headers=auth)

    (tmp_path / "installed").write_text("x")
    assert call("GET", CLIENT_TG).status_code == 403
    assert call("POST", ADMIN_TG, **{"X-View-As": "client"}).status_code == 403
    assert call("GET", ADMIN_TG).json()["installed"] is True
    assert call("POST", ADMIN_TG).json()["requested"] is True

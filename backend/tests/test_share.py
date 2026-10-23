"""«Поделиться»: a picture goes to the admin's own Telegram, never to the client."""

import json

import httpx
import pytest
from conftest import ADMIN_TG, CLIENT_TG
from test_api import api, blobs  # noqa: F401  (fixtures)

from crm.services import telegram_share
from crm.services.telegram_share import ShareError, TelegramShare


def _telegram(calls, fail=()):
    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        calls.append(method)
        if method in fail:
            return httpx.Response(200, json={"ok": False, "description": "Bad Request"})
        result = {
            "sendPhoto": {"message_id": 7, "photo": [{"file_id": "small"}, {"file_id": "big"}]},
            "savePreparedInlineMessage": {"id": "prep-1", "expiration_date": 0},
            "deleteMessage": True,
        }[method]
        if method == "savePreparedInlineMessage":
            body = json.loads(request.content)
            assert body["user_id"] == ADMIN_TG and body["result"]["photo_file_id"] == "big"
        return httpx.Response(200, json={"ok": True, "result": result})

    return httpx.MockTransport(handler)


def test_picker_prepares_message_and_removes_the_chat_copy():
    calls = []
    share = TelegramShare("t", transport=_telegram(calls))
    assert share.share_photo(ADMIN_TG, b"png", picker=True) == "prep-1"
    assert calls == ["sendPhoto", "savePreparedInlineMessage", "deleteMessage"]


def test_without_picker_the_picture_stays_in_the_chat():
    calls = []
    share = TelegramShare("t", transport=_telegram(calls))
    assert share.share_photo(ADMIN_TG, b"png", picker=False) is None
    assert calls == ["sendPhoto"]


def test_failed_prepare_keeps_the_picture_to_forward():
    calls = []
    share = TelegramShare("t", transport=_telegram(calls, fail={"savePreparedInlineMessage"}))
    assert share.share_photo(ADMIN_TG, b"png", picker=True) is None
    assert "deleteMessage" not in calls


def test_send_failure_is_a_readable_error():
    share = TelegramShare("t", transport=_telegram([], fail={"sendPhoto"}))
    with pytest.raises(ShareError):
        share.share_photo(ADMIN_TG, b"png", picker=True)


def test_share_endpoint_is_admin_only(api, monkeypatch):  # noqa: F811
    sent = []
    monkeypatch.setattr(
        telegram_share.TelegramShare,
        "share_photo",
        lambda self, user, data, picker: sent.append((user, picker)) or "prep-9",
    )
    files = {"file": ("crm.png", b"png", "image/png")}
    assert api("POST", "/api/share", who=CLIENT_TG, files=files).status_code == 403
    response = api("POST", "/api/share", files=files)
    assert response.status_code == 200
    assert response.json() == {"prepared_id": "prep-9", "in_chat": False}
    assert sent == [(ADMIN_TG, True)]


def test_download_link_serves_the_picture_once_uploaded(api):  # noqa: F811
    files = {"file": ("crm.png", b"\x89PNG-data", "image/png")}
    assert api("POST", "/api/share/file", who=CLIENT_TG, files=files).status_code == 403
    url = api("POST", "/api/share/file", files=files).json()["url"]
    got = api("GET", url, who=None)
    assert got.status_code == 200 and got.content == b"\x89PNG-data"
    assert got.headers["content-type"] == "image/png"
    assert api("GET", "/api/share/file/nope.png", who=None).status_code == 404

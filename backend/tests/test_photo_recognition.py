"""The Mini App's "Распознать" button: Gemini reads an uploaded photo and only
suggests fields; nothing is saved."""

import io

import pytest
from conftest import ADMIN_TG, CLIENT_TG
from fastapi.testclient import TestClient
from PIL import Image

from crm.api.app import ApiConfig, create_app
from crm.api.telegram_auth import make_init_data
from crm.services.container import build_services
from crm.services.recognition import Recognition, RecognitionError
from crm.storage.blobs import MemoryBlobStorage

BOT_TOKEN = "123456:TEST-token"
pytestmark = pytest.mark.usefixtures("client_doc")


class FakeGemini:
    engine = "fake-gemini"

    def __init__(self, answer: Recognition | Exception):
        self.answer = answer
        self.images: list[bytes] = []

    def recognize(self, image: bytes, text: str | None) -> Recognition:
        self.images.append(image)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), (200, 30, 30)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _api(db, clock, recognizer):
    services = build_services(
        db, frozenset({ADMIN_TG}), clock, blob_storage=MemoryBlobStorage(), recognizer=recognizer
    )
    client = TestClient(create_app(services, ApiConfig(bot_token=BOT_TOKEN)))

    def call(method: str, path: str, who: int = ADMIN_TG, **kwargs):
        headers = {"Authorization": f"tma {make_init_data(who, BOT_TOKEN)}"}
        return client.request(method, path, headers=headers, **kwargs)

    return call


def _upload(api) -> str:
    uploaded = api("POST", "/api/images", files={"file": ("p.jpg", _jpeg(), "image/jpeg")})
    return uploaded.json()["photo_url"]


def test_uploaded_photo_is_recognised_without_saving_anything(db, clock):
    gemini = FakeGemini(
        Recognition(brand="Nike", model="Dunk Low Panda", size="270", confidence=0.9, engine="g")
    )
    api = _api(db, clock, gemini)
    assert api("GET", "/api/settings").json()["recognition_enabled"] is True
    photo_url = _upload(api)

    answer = api("POST", "/api/recognize", json={"photo_url": photo_url}).json()

    assert answer["recognized"] is True
    assert (answer["brand"], answer["model"], answer["size"]) == ("Nike", "Dunk Low Panda", "270")
    # Gemini saw the stored (processed WebP) photo.
    assert gemini.images[0][:4] == b"RIFF"
    assert db.query("orders") == []


def test_only_admin_can_recognise(db, clock):
    api = _api(db, clock, FakeGemini(Recognition(brand="Nike", confidence=0.9)))
    photo_url = _upload(api)
    denied = api("POST", "/api/recognize", who=CLIENT_TG, json={"photo_url": photo_url})
    assert denied.status_code == 403


def test_clear_errors_for_missing_photo_key_or_gemini_failure(db, clock):
    api = _api(db, clock, FakeGemini(RecognitionError("превышен лимит запросов Gemini")))
    missing = api("POST", "/api/recognize", json={"photo_url": "memory://nope.webp"})
    assert missing.status_code == 404 and "загрузите" in missing.json()["error"]["message"]
    failed = api("POST", "/api/recognize", json={"photo_url": _upload(api)})
    assert "лимит" in failed.json()["error"]["message"]

    no_key = _api(db, clock, None)
    assert no_key("GET", "/api/settings").json()["recognition_enabled"] is False
    refused = no_key("POST", "/api/recognize", json={"photo_url": "memory://x.webp"})
    assert "GEMINI_API_KEY" in refused.json()["error"]["message"]

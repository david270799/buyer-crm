"""Gemini recognition: request format, validation of the answer, fallbacks."""

import base64
import json

import httpx
import pytest

from crm.services.recognition import (
    GeminiRecognizer,
    RecognitionError,
    extract_urls,
    fallback,
    find_sizes,
    recognize_safely,
    validate,
)

CAPTION = "42 https://shop.example.kr/item/123"


def gemini_reply(answer: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}]}


def answer(**fields) -> dict:
    base = {
        "is_product": True,
        "brand": "Nike",
        "model": "Dunk Low Retro 'Panda'",
        "category": "кроссовки",
        "size": "42",
        "size_source": "text",
        "link": "https://shop.example.kr/item/123",
        "note": None,
        "confidence": 0.93,
    }
    return {**base, **fields}


def recognizer(handler, **kwargs) -> GeminiRecognizer:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GeminiRecognizer("test-key", "gemini-test", client=client, backoff_seconds=0, **kwargs)


# --- validation --------------------------------------------------------------


def test_trusted_answer_is_kept():
    result = validate(answer(), CAPTION, "gemini-test")
    assert (result.brand, result.model, result.size) == ("Nike", "Dunk Low Retro 'Panda'", "42")
    assert result.link == "https://shop.example.kr/item/123"
    assert result.recognized and result.engine == "gemini-test"


def test_low_confidence_leaves_brand_and_model_empty():
    result = validate(answer(confidence=0.4), CAPTION, "g")
    assert result.brand is None and result.model is None
    assert result.size == "42"  # the size is the client's own words


def test_invented_link_is_dropped():
    result = validate(answer(link="https://fake.example/x"), CAPTION, "g")
    assert result.link == "https://shop.example.kr/item/123"  # the one actually in the caption
    assert validate(answer(link="https://fake.example/x"), "42", "g").link is None


def test_size_must_be_in_the_caption_or_seen_in_the_photo():
    assert validate(answer(size="43"), CAPTION, "g").size == "42"  # caption wins
    assert validate(answer(size="43"), "без размера", "g").size is None
    assert validate(answer(size="270", size_source="image"), "", "g").size == "270"
    assert validate(answer(size="270", size_source="image", confidence=0.3), "", "g").size is None


def test_placeholders_and_long_values_are_cleaned():
    result = validate(answer(brand="unknown", model="x" * 500, note="  срочно  "), CAPTION, "g")
    assert result.brand is None and len(result.model) == 120 and result.note == "срочно"


def test_clear_non_product_is_flagged():
    assert validate(answer(is_product=False, confidence=0.95), "", "g").not_a_product
    assert not validate(answer(is_product=False, confidence=0.5), "", "g").not_a_product


def test_caption_helpers():
    assert extract_urls("see https://a.kr/x, and https://b.kr/y).") == [
        "https://a.kr/x",
        "https://b.kr/y",
    ]
    assert find_sizes("размер 42.5") == ["42.5"]
    assert find_sizes("270 мм") == ["270"]
    assert find_sizes("US 9, M") == ["US 9", "M"]
    assert find_sizes("цена 150000, 2 пары") == []
    assert find_sizes("https://shop.kr/p/270") == []


def test_fallback_takes_only_unambiguous_values():
    single = fallback(CAPTION)
    assert (single.size, single.link) == ("42", "https://shop.example.kr/item/123")
    assert single.engine is None
    assert fallback("42 или 43").size is None


# --- the HTTP call -------------------------------------------------------------


def test_request_contains_the_photo_caption_schema_and_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=gemini_reply(answer()))

    result = recognizer(handler).recognize(b"WEBPDATA", CAPTION)

    assert result.brand == "Nike"
    assert seen["url"].endswith("/models/gemini-test:generateContent")
    assert seen["key"] == "test-key" and "test-key" not in seen["url"]
    parts = seen["body"]["contents"][0]["parts"]
    assert base64.b64decode(parts[0]["inlineData"]["data"]) == b"WEBPDATA"
    assert parts[0]["inlineData"]["mimeType"] == "image/webp"
    assert CAPTION in parts[1]["text"]
    config = seen["body"]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert "brand" in config["responseSchema"]["properties"]


def test_transient_errors_are_retried():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return httpx.Response(200, json=gemini_reply(answer()))

    assert recognizer(handler).recognize(b"x", CAPTION).recognized
    assert len(calls) == 3


def test_bad_key_fails_without_retry_and_never_shows_the_key():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(403, json={"error": {"message": "API key not valid"}})

    with pytest.raises(RecognitionError) as exc:
        recognizer(handler).recognize(b"x", CAPTION)
    assert "GEMINI_API_KEY" in str(exc.value) and "test-key" not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {"candidates": []},
        {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]},
        {"candidates": [{"content": {"parts": [{"text": "[1, 2]"}]}}]},
    ],
)
def test_unusable_answers_fall_back_to_the_caption(payload):
    def handler(request):
        return httpx.Response(200, json=payload)

    result = recognize_safely(recognizer(handler), b"x", CAPTION)

    assert result.engine is None and result.error
    assert (result.size, result.link) == ("42", "https://shop.example.kr/item/123")


def test_network_failure_falls_back():
    def handler(request):
        raise httpx.ConnectError("offline")

    result = recognize_safely(recognizer(handler, retries=1), b"x", "43")
    assert result.error.startswith("нет связи") and result.size == "43"


def test_no_key_means_caption_only():
    result = recognize_safely(None, b"x", "M")
    assert result.size == "M" and "GEMINI_API_KEY" in result.error


@pytest.mark.parametrize(
    ("caption", "sizes"),
    [
        ("42, срочно", ["42"]),
        ("42,5", ["42,5"]),
        ("42 или 43", ["42", "43"]),
        ("EU 43 (US 9.5)", ["EU 43", "US 9.5"]),
        ("размер: 38", ["38"]),
        ("1 пара 250000 вон", []),
    ],
)
def test_size_patterns(caption, sizes):
    assert find_sizes(caption) == sizes


def test_key_check_uses_the_model_endpoint():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url)))
        status = 200 if request.headers.get("x-goog-api-key") == "test-key" else 400
        return httpx.Response(status, json={"name": "models/gemini-test"})

    recognizer(handler).check()
    assert seen == [("GET", "https://generativelanguage.googleapis.com/v1beta/models/gemini-test")]
    bad = GeminiRecognizer(
        "wrong", "gemini-test", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(RecognitionError):
        bad.check()

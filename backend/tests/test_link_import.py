import io

import httpx
import pytest
from PIL import Image

from crm.domain.enums import Role
from crm.domain.errors import PermissionDeniedError, ValidationError
from crm.services.common import Actor
from crm.services.link_import import (
    LinkError,
    LinkImportService,
    PageFetcher,
    PageInfo,
    parse_page,
)
from crm.services.recognition import RecognitionError

ADMIN = Actor.telegram(1, Role.ADMIN)
CLIENT = Actor.telegram(2, Role.CLIENT)

PAGE = """<!doctype html><html><head>
<title>나이키 덩크 로우 | Shop</title>
<meta property="og:title" content="나이키 덩크 로우 레트로 판다">
<meta property="og:image" content="/img/dunk.jpg">
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":"Product","name":"Nike Dunk Low Retro",
"brand":{"@type":"Brand","name":"Nike"},"image":["https://cdn.shop.kr/dunk.jpg"]}]}
</script></head><body>...</body></html>"""


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (60, 40), "red").save(buffer, "JPEG")
    return buffer.getvalue()


def test_parse_page_prefers_json_ld_product():
    info = parse_page(PAGE, "https://shop.kr/p/1")
    assert info.title == "Nike Dunk Low Retro"
    assert info.brand == "Nike"
    assert info.image_url == "https://cdn.shop.kr/dunk.jpg"


def test_parse_page_falls_back_to_open_graph():
    info = parse_page(PAGE.split("<script")[0], "https://shop.kr/p/1")
    assert info.title == "나이키 덩크 로우 레트로 판다"
    assert info.image_url == "https://shop.kr/img/dunk.jpg"


def test_internal_addresses_are_refused():
    fetcher = PageFetcher(
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    )
    for url in ("http://127.0.0.1:8080/", "http://10.0.0.5/", "http://169.254.169.254/", "ftp://x"):
        with pytest.raises(LinkError):
            fetcher.page(url)


def test_redirect_to_an_internal_address_is_refused():
    def handler(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    fetcher = PageFetcher(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(LinkError):
        fetcher.page("http://93.184.216.34/item")


def test_page_is_read_through_a_public_address():
    def handler(request):
        return httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})

    fetcher = PageFetcher(httpx.Client(transport=httpx.MockTransport(handler)))
    assert fetcher.page("http://93.184.216.34/item").brand == "Nike"


class FakeFetcher:
    def __init__(self, page: PageInfo):
        self._page = page

    def page(self, url):
        return self._page

    def image(self, url):
        return _jpeg()


class FakeGemini:
    engine = "gemini-fake"

    def __init__(self, confidence=0.9, fail=False):
        self.confidence, self.fail, self.calls = confidence, fail, []

    def read_listing(self, image, text):
        self.calls.append((image is not None, text))
        if self.fail:
            raise RecognitionError("лимит")
        return {
            "brand": "Nike",
            "model": "Dunk Low 'Panda'",
            "category": "кроссовки",
            "confidence": self.confidence,
        }


def test_import_fills_english_names_and_photo():
    gemini = FakeGemini()
    page = PageInfo(title="나이키 덩크", image_url="https://cdn/x.jpg", site="shop.kr")
    result = LinkImportService(None, gemini, FakeFetcher(page)).import_link(
        ADMIN, "https://shop.kr/1"
    )
    assert (result.brand, result.model) == ("Nike", "Dunk Low 'Panda'")
    assert gemini.calls[0][0] is True and "나이키 덩크" in gemini.calls[0][1]
    assert result.note is None


def test_unsure_gemini_leaves_names_empty():
    page = PageInfo(title="뭔가", site="shop.kr")
    result = LinkImportService(None, FakeGemini(0.3), FakeFetcher(page)).import_link(
        ADMIN, "https://shop.kr/1"
    )
    assert result.brand is None and result.model is None and "не уверен" in result.note


def test_closed_shop_and_rights():
    service = LinkImportService(None, FakeGemini(), FakeFetcher(PageInfo()))
    with pytest.raises(ValidationError):
        service.import_link(ADMIN, "https://shop.kr/1")
    with pytest.raises(PermissionDeniedError):
        service.import_link(CLIENT, "https://shop.kr/1")


class KoreanGemini(FakeGemini):
    """Answers in Korean first, in English when asked again."""

    def read_listing(self, image, text):
        self.calls.append((image is not None, text))
        if "MUST be in English" in text:
            return {"brand": "Nike", "model": "Dunk Low", "category": None, "confidence": 0.9}
        return {"brand": "나이키", "model": "덩크 로우", "category": None, "confidence": 0.9}


def test_korean_answer_is_translated_on_a_second_try():
    gemini = KoreanGemini()
    page = PageInfo(title="나이키 덩크 로우", site="shop.kr")
    result = LinkImportService(None, gemini, FakeFetcher(page)).import_link(ADMIN, "https://s.kr/1")
    assert (result.brand, result.model) == ("Nike", "Dunk Low")
    assert len(gemini.calls) == 2


def test_korean_never_reaches_the_form():
    class StubbornGemini(FakeGemini):
        def read_listing(self, image, text):
            return {"brand": "나이키", "model": "덩크", "category": None, "confidence": 0.9}

    page = PageInfo(title="나이키 덩크", brand="나이키", site="shop.kr")
    for gemini in (StubbornGemini(), FakeGemini(fail=True), None):
        result = LinkImportService(None, gemini, FakeFetcher(page)).import_link(
            ADMIN, "https://s.kr/1"
        )
        assert result.brand is None and result.model is None

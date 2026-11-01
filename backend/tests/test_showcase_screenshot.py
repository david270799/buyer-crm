"""«Витрина» from a shop screenshot (the owner, 01.11.2026)."""

import io

import pytest
from PIL import Image
from test_showcase import FakeImages

from crm.domain.errors import PermissionDeniedError, ValidationError
from crm.repositories import ShowcaseRepository
from crm.services.link_import import LinkError
from crm.services.screenshots import crop, page_has_code
from crm.services.showcase_service import CartLine, ShowcaseService

pytestmark = pytest.mark.usefixtures("client_doc")

JACKET = {
    "is_product": True,
    "brand": "The North Face",
    "model": "Men's Hailstone Jacket Black",
    "code": "NJ3BS51A",
    "price_krw": 158_840,
    "original_price_krw": 209_000,
    "category": "куртка",
    "photo_box": [100, 0, 530, 1000],
    "confidence": 0.95,
}
PAGE = "https://www.thenorthfacekorea.co.kr/product/NJ3BS51A"


def _screenshot() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (857, 2000), (250, 250, 250)).save(buffer, format="JPEG")
    return buffer.getvalue()


class FakeGemini:
    def __init__(self, answer=JACKET, pages=(PAGE,)):
        self.answer = dict(answer)
        self.pages = list(pages)
        self.searched = None

    def read_screenshot(self, image, mime="image/jpeg"):
        assert image[:2] == b"\xff\xd8"  # a plain JPEG, not squared
        return self.answer

    def find_product_pages(self, product):
        self.searched = product
        return self.pages


class FakeFetcher:
    def __init__(self, html):
        self.html_text = html
        self.opened = []

    def html(self, url):
        self.opened.append(url)
        if "broken" in url:
            raise LinkError("HTTP 403")
        return self.html_text, url

    def image(self, url):
        buffer = io.BytesIO()
        Image.new("RGB", (800, 800), (20, 20, 20)).save(buffer, format="JPEG")
        return buffer.getvalue()


PRODUCT_HTML = (
    '<html><head><meta property="og:image" content="https://cdn.example/nj3bs51a_1.jpg">'
    "<title>NJ3BS51A 남성 헤일스톤 자켓</title></head><body>NJ3BS51A-BLK</body></html>"
)


def make(db, services, clock, gemini, html=PRODUCT_HTML):
    return ShowcaseService(
        db,
        clock,
        ShowcaseRepository(),
        services.orders,
        services.orders._auditor,
        FakeImages(),
        gemini,
        FakeFetcher(html),
    )


def test_screenshot_becomes_a_draft_with_its_price_and_web_photos(db, services, clock, admin):
    gemini = FakeGemini(pages=("https://broken.example/x", PAGE))
    showcase = make(db, services, clock, gemini)
    item = showcase.add_screenshot(admin, _screenshot())
    assert item.status == "draft" and item.from_screenshot
    assert (item.brand, item.model, item.code) == (
        "The North Face",
        "Men's Hailstone Jacket Black",
        "NJ3BS51A",
    )
    assert item.category == "clothes"
    # The price exactly as on the screenshot, no markup; the crossed-out one kept.
    assert item.shop_price_krw == 158_840 and item.client_price_krw == 158_840
    assert item.official_price_krw == 209_000
    assert item.url == PAGE and item.photos and item.sizes == []
    assert "NJ3BS51A" in gemini.searched
    assert item.note is None  # no notes on such cards (the owner, 02.11.2026)


def test_no_page_with_the_code_takes_the_photo_from_the_screenshot(db, services, clock, admin):
    other = PRODUCT_HTML.replace("NJ3BS51A", "NJ3BS99Z").replace("nj3bs51a", "nj3bs99z")
    showcase = make(db, services, clock, FakeGemini(), html=other)
    item = showcase.add_screenshot(admin, _screenshot())
    assert item.url == "" and item.photos  # cut out of the screenshot
    assert item.note is None


def test_sizes_are_typed_in_and_the_shop_is_never_reread(db, services, clock, admin, client_actor):
    showcase = make(db, services, clock, FakeGemini())
    item = showcase.add_screenshot(admin, _screenshot())
    with pytest.raises(ValidationError):
        showcase.refresh(admin, item.id)  # the admin is told why
    item = showcase.update(admin, item.id, {"sizes": ["95", "100", " 100 ", "105 (L)"]})
    assert [s["name"] for s in item.sizes] == ["95", "100", "105 (L)"]
    showcase.set_status(admin, item.id, "published")
    assert showcase.refresh(client_actor, item.id).shop_price_krw == 158_840  # untouched
    showcase.order(client_actor, [CartLine(item.id, "100")])
    order = db.get("orders", "N1")
    assert "100" in (order.get("size"), order.get("size_kr"))


def test_typed_sizes_only_on_screenshot_cards(db, services, clock, admin):
    showcase = make(db, services, clock, FakeGemini())
    item = showcase.add_screenshot(admin, _screenshot())
    db.run_transaction(lambda tx: tx.update("showcase", item.id, {"source": None}))
    with pytest.raises(ValidationError):
        showcase.update(admin, item.id, {"sizes": ["M"]})


def test_not_a_product_or_no_price_or_not_admin(db, services, clock, admin, client_actor):
    with pytest.raises(ValidationError):
        make(db, services, clock, FakeGemini({**JACKET, "price_krw": None})).add_screenshot(
            admin, _screenshot()
        )
    with pytest.raises(ValidationError):
        make(db, services, clock, FakeGemini({**JACKET, "is_product": False})).add_screenshot(
            admin, _screenshot()
        )
    with pytest.raises(PermissionDeniedError):
        make(db, services, clock, FakeGemini()).add_screenshot(client_actor, _screenshot())


def test_helpers():
    assert page_has_code("<p>nj3bs51a-blk</p>", "NJ3BS51A")
    assert not page_has_code("<p>NJ3BS52A</p>", "NJ3BS51A")
    assert not page_has_code("anything", "AB")  # too short to prove anything
    assert crop(_screenshot(), [100, 0, 105, 1000]) is None  # a sliver is not a photo
    piece = Image.open(io.BytesIO(crop(_screenshot(), [100, 0, 530, 1000])))
    assert piece.size == (857, 860)


def test_photos_are_searched_again_and_arranged_by_hand(db, services, clock, admin):
    """The owner (02.11.2026): «найти фото» again and own photos from the gallery."""
    other = PRODUCT_HTML.replace("NJ3BS51A", "NJ3BS99Z").replace("nj3bs51a", "nj3bs99z")
    showcase = make(db, services, clock, FakeGemini(), html=other)
    item = showcase.add_screenshot(admin, _screenshot())  # only the cut-out photo
    cut = item.photos[0]
    again, found = showcase.search_photos(admin, item.id)
    assert found == 0 and again.photos == [cut]
    showcase._fetcher.html_text = PRODUCT_HTML  # the shop page appeared
    again, found = showcase.search_photos(admin, item.id)
    assert found >= 1 and again.photos[-1] == cut and again.url == PAGE
    own = {"photo_url": "/media/images/own.webp", "thumbnail_url": "/media/images/own_t.webp"}
    item = showcase.update(admin, item.id, {"photos": [own, cut]})
    assert item.photos == [own, cut] and item.photo_url == own["photo_url"]
    with pytest.raises(ValidationError):
        showcase.update(admin, item.id, {"photos": [{"photo_url": "javascript:alert(1)"}]})
    db.run_transaction(lambda tx: tx.update("showcase", item.id, {"code": None}))
    with pytest.raises(ValidationError):
        showcase.search_photos(admin, item.id)


SWATCH = "https://static.swatch.com/images/product/SYXS106"
SWATCH_HTML = (
    "<html><head>"
    '<meta property="og:title" content="SKINBLUEIRON - SYXS106 - Swatch® Official Store">'
    f'<meta property="og:image" content="{SWATCH}/sa200/SYXS106_sa200_er005.png"></head><body>'
    f'<img src="{SWATCH}/sa200/SYXS106_sa200_er006.png">'
    f'<img src="{SWATCH}/sa000/SYXS106_sa000_er003.png">'
    f'<img src="{SWATCH}/sa000/SYXS106_sa000_er003m.png">'
    f'<img src="{SWATCH}/sa360/SYXS106_36.png">'
    "</body></html>"
)


def test_swatch_gallery_is_read_whole():
    from crm.services.offers import photo_candidates

    urls = photo_candidates(
        SWATCH_HTML,
        "https://www.swatch.com/en-en/x/SYXS106.html",
        f"{SWATCH}/sa200/SYXS106_sa200_er005.png",
    )
    assert urls == [
        f"{SWATCH}/sa200/SYXS106_sa200_er005.png",
        f"{SWATCH}/sa200/SYXS106_sa200_er006.png",
        f"{SWATCH}/sa000/SYXS106_sa000_er003.png",
    ]  # no 360° frames, no «m» copies


def test_a_model_number_makes_a_card_from_the_brand_page(db, services, clock, admin):
    """The owner (02.11.2026): «SYXS106» → the Swatch page → photos."""
    from crm.services.showcase_service import model_code

    assert model_code(" syxs106 ") == "SYXS106"
    assert model_code("260") is None and model_code("Air") is None and model_code("N5") is None
    showcase = make(db, services, clock, FakeGemini(pages=()), html=SWATCH_HTML)
    item = showcase.add_by_code(admin, "syxs106")
    assert showcase._fetcher.opened[0] == "https://www.swatch.com/en-en/SYXS106.html"
    assert item.code == "SYXS106" and item.brand == "Swatch" and item.category == "watch"
    assert len(item.photos) == 3 and item.status == "draft"
    with pytest.raises(ValidationError):
        make(db, services, clock, FakeGemini(pages=()), html="<p>nothing</p>").add_by_code(
            admin, "SYXS999"
        )


def test_a_watch_screenshot_goes_to_the_brand_site_first(db, services, clock, admin):
    """The owner (02.11.2026): a Swatch screenshot → swatch.com by the number,
    photos and the name from there, the price from the screenshot."""
    watch = {
        **JACKET,
        "brand": "Swatch",
        "model": "Men's Watch",
        "code": "SYXS106",
        "price_krw": 190_000,
        "original_price_krw": 289_000,
        "category": None,
    }
    gemini = FakeGemini(watch, pages=())
    showcase = make(db, services, clock, gemini, html=SWATCH_HTML)
    item = showcase.add_screenshot(admin, _screenshot())
    assert showcase._fetcher.opened[0] == "https://www.swatch.com/en-en/SYXS106.html"
    assert (item.brand, item.model, item.category) == ("Swatch", "Skinblueiron", "watch")
    assert item.client_price_krw == 190_000 and len(item.photos) == 3

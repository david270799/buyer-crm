import io
from pathlib import Path

import pytest
from conftest import START_BALANCE, balance
from PIL import Image

from crm.domain.errors import ConflictError, PermissionDeniedError, ValidationError
from crm.repositories import ShowcaseRepository
from crm.services.offers import better_image_url, parse_offer
from crm.services.showcase_service import CartLine, ShowcaseService, shop_name

pytestmark = pytest.mark.usefixtures("client_doc")

HMALL_HTML = (Path(__file__).parent / "fixtures" / "hmall_item.html").read_text()
COLOR_HTML = (Path(__file__).parent / "fixtures" / "hmall_color_size.html").read_text()
URL = "https://www.hmall.com/md/pda/itemPtc?slitmCd=2249340866"


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (300, 300), (240, 240, 240)).save(buffer, format="JPEG")
    return buffer.getvalue()


class FakeFetcher:
    def __init__(self, html=HMALL_HTML):
        self.page_html = html
        self.images = []
        self.answers = {}  # URL part → JSON (Hmall colour / size answers)

    def json(self, url):
        from crm.services.link_import import LinkError

        for part, answer in self.answers.items():
            if part in url:
                return answer
        raise LinkError("Сайт ответил ошибкой (HTTP 404).")

    def html(self, url):
        return self.page_html, url

    def image(self, url):
        from crm.services.link_import import LinkError

        self.images.append(url)
        if "_3.jpg" in url:  # this product has 3 photos: _0, _1, _2
            raise LinkError("Сайт ответил ошибкой (HTTP 404).")
        return _jpeg()


class FakeGemini:
    engine = "fake"
    official = {"price_krw": 79_000, "url": "https://www.adidas.co.kr/kf8282.html"}

    def find_official_price(self, product):
        self.asked = product
        return self.official

    def read_listing(self, image, text):
        return {
            "brand": "Adidas",
            "model": "KF8282 STSV Track Top",
            "category": "одежда",
            "confidence": 0.9,
        }


class FakeImages:
    def store_processed(self, main, thumb, size, *, folder, jpeg=False):
        from crm.services.image_service import StoredImage

        return StoredImage(f"/media/{folder}/p.webp", f"/media/{folder}/t.webp", 1, 1, 1, 1)


@pytest.fixture
def showcase(db, services, clock):
    fetcher = FakeFetcher()
    service = ShowcaseService(
        db,
        clock,
        ShowcaseRepository(),
        services.orders,
        services.orders._auditor,
        FakeImages(),
        FakeGemini(),
        fetcher,
    )
    service.fetcher = fetcher
    return service


def test_hmall_page_gives_price_and_sizes():
    offer = parse_offer(HMALL_HTML)
    assert offer.price_krw == 53_400
    assert [(s.name, s.stock) for s in offer.sizes] == [("XS", 5), ("S", 10), ("M", 9), ("L", 2)]
    assert better_image_url("https://image.hmall.com/x.jpg?RS=300x300").endswith("RS=1000x1000")
    assert shop_name(URL) == "Hmall"


def test_link_becomes_a_draft_with_photo_name_price_and_sizes(showcase, admin):
    item = showcase.add(admin, URL)
    assert item.status == "draft" and item.shop == "Hmall" and item.url == URL
    assert (item.brand, item.model, item.category) == ("Adidas", "KF8282 STSV Track Top", "clothes")
    assert item.shop_price_krw == 53_400 and item.photo_url
    assert [s["name"] for s in item.sizes] == ["XS", "S", "M", "L"]
    assert "RS=1000x1000" in showcase.fetcher.images[0]
    assert item.client_price_krw == 53_400  # no markup yet


def test_markup_and_manual_price(showcase, admin):
    item = showcase.add(admin, URL)
    assert showcase.update(admin, item.id, {"markup_value": 20_000}).client_price_krw == 73_400
    pct = showcase.update(admin, item.id, {"markup_type": "pct", "markup_value": 15})
    assert pct.client_price_krw == 61_500  # 61,410 rounded up to ₩ 100
    fixed = showcase.update(
        admin, item.id, {"client_price_override": 70_000, "shop_price_krw": 50_000}
    )
    assert fixed.client_price_krw == 70_000 and fixed.shop_price_krw == 50_000
    with pytest.raises(ValidationError):
        showcase.update(admin, item.id, {"markup_value": 500})


def test_publish_order_makes_new_orders_without_money(db, showcase, admin):
    item = showcase.add(admin, URL)
    showcase.update(admin, item.id, {"markup_value": 20_000})
    with pytest.raises(ConflictError):
        showcase.order(admin, [CartLine(item.id, "M")])  # not published yet
    showcase.set_status(admin, item.id, "published")
    with pytest.raises(ValidationError):
        showcase.order(admin, [CartLine(item.id, "XXL")])

    [order] = showcase.order(admin, [CartLine(item.id, "M")])
    stored = db.get("orders", order.id)
    assert stored["status"] == "new" and stored["showcase_id"] == item.id
    assert stored["source_url"] == URL and stored["shop"] == "Hmall" and stored["size"] == "M"
    assert stored["client_price"] == 73_400 and stored.get("charged_amount_krw", 0) == 0
    assert "Из витрины" in stored["internal_comment"]
    assert balance(db) == START_BALANCE


def test_refresh_likes_delete_and_admin_only(db, showcase, admin, client_actor):
    item = showcase.add(admin, URL)
    showcase.fetcher.page_html = HMALL_HTML.replace(
        '"sumUitmAttrNmStockCnt":2', '"sumUitmAttrNmStockCnt":0'
    )
    refreshed = showcase.refresh(admin, item.id)
    assert {s["name"]: s["available"] for s in refreshed.sizes}["L"] is False
    assert showcase.toggle_like(admin, item.id) == [item.id]
    assert showcase.toggle_like(admin, item.id) == []
    with pytest.raises(PermissionDeniedError):
        showcase.items(client_actor)
    showcase.delete(admin, item.id)
    assert showcase.items(admin) == []


def test_page_without_data_still_makes_a_draft(showcase, admin):
    showcase.fetcher.page_html = "<html><head><title>Item</title></head></html>"
    item = showcase.add(admin, "https://shop.example.kr/1")
    assert item.shop_price_krw is None and "цена не найдена" in item.note
    with pytest.raises(ConflictError):
        showcase.set_status(admin, item.id, "published")


def test_official_price_is_taken_only_from_the_brand_site(showcase, admin):
    item = showcase.add(admin, URL)
    assert item.official_price_krw == 79_000 and "adidas.co.kr" in item.official_url

    showcase._recognizer.official = {"price_krw": 49_000, "url": "https://reseller.example/x"}
    again = showcase.find_official(admin, item.id)
    assert again.official_price_krw == 79_000  # a reseller page is not «official»
    assert "не найдена" in again.note


def test_statistics_count_opens_likes_and_orders(showcase, admin):
    item = showcase.add(admin, URL)
    showcase.set_status(admin, item.id, "published")
    for _ in range(3):
        showcase.viewed(admin, item.id)
    showcase.toggle_like(admin, item.id)
    showcase.order(admin, [CartLine(item.id, "S")])

    showcase.toggle_like(admin, item.id)  # ♥ off …
    showcase.toggle_like(admin, item.id)  # … and on again

    stats = showcase.statistics(admin)
    [card] = stats["cards"]
    assert (card["item_id"], card["views"], card["liked"]) == (item.id, 3, True)
    assert card["last_at"] is not None
    kinds = [h["kind"] for h in stats["history"]]
    assert sorted(kinds) == sorted(["view"] * 3 + ["like", "unlike", "like", "order"])
    order = next(h for h in stats["history"] if h["kind"] == "order")
    assert order["size"] == "S" and order["order_id"] and order["viewer"] == admin.id
    assert stats["items"][item.id]["title"] == item.title_line


def test_all_product_photos_are_kept_up_to_the_first_gap(showcase, admin):
    item = showcase.add(admin, URL)
    assert len(item.photos) == 3
    assert item.photo_url == item.photos[0]["photo_url"]
    assert not any("_4.jpg" in u for u in showcase.fetcher.images)  # stopped at the gap


def test_a_burst_of_links_reads_at_most_two_pages_at_once(showcase, admin):
    import threading
    import time

    from crm.services.showcase_service import READ_PARALLEL

    lock, state = threading.Lock(), {"now": 0, "peak": 0}
    page = showcase.fetcher.html

    def slow_html(url):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return page(url)

    showcase.fetcher.html = slow_html
    threads = [threading.Thread(target=showcase.add, args=(admin, URL)) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert state["peak"] == READ_PARALLEL == 2
    assert len(showcase.items(admin, "draft")) == 6


def _fixture(name):
    import json

    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def test_colour_then_size_product_gets_every_pair_with_stock(showcase, admin):
    # The owner, 20.10.2026: on Hmall a jacket is chosen colour first, then
    # size; the page itself lists only the colours (stock 0 for each).
    showcase.fetcher.page_html = COLOR_HTML
    showcase.fetcher.answers = {
        "uitm-attr-type": _fixture("hmall_color_size_attr.json"),
        "item-stockcount": _fixture("hmall_color_size_stock.json"),
    }
    item = showcase.add(admin, "https://www.hmall.com/md/pda/itemPtc?slitmCd=2245070800")
    assert item.shop_price_krw == 79_000
    black = [(s["name"], s["stock"]) for s in item.sizes if s["color"] == "NJ5JR66A_BLK"]
    assert black == [
        ("090(S)", 16),
        ("095(M)", 37),
        ("100(L)", 57),
        ("105(XL)", 19),
        ("110(XXL)", 19),
    ]
    charcoal_xxl = next(
        s for s in item.sizes if s["color"] == "NJ5JR66B_CHC" and s["name"] == "110(XXL)"
    )
    assert charcoal_xxl["available"] is False  # Hmall: sold out (not on sale)
    assert len({s["color"] for s in item.sizes}) == 3 and len(item.sizes) == 15

    showcase.set_status(admin, item.id, "published")
    with pytest.raises(ValidationError, match="цвет"):
        showcase.order(admin, [CartLine(item.id, "090(S)")])
    [order] = showcase.order(admin, [CartLine(item.id, "095(M)", "NJ5JR66B_CHC")])
    assert order.model.endswith("· NJ5JR66B_CHC")
    assert (order.size, order.size_kr) == ("M", "095")


def test_colour_answers_failing_keep_the_page_list(showcase, admin):
    showcase.fetcher.page_html = COLOR_HTML
    item = showcase.add(admin, "https://www.hmall.com/md/pda/itemPtc?slitmCd=2245070800")
    assert [s["name"] for s in item.sizes] == ["NJ5JR66A_BLK", "NJ5JR66B_CHC", "NJ5JR66C_DBE"]


def test_naver_blocking_programs_gets_a_plain_message(showcase, admin):
    from crm.services.link_import import LinkError

    def blocked(url):
        raise LinkError("Сайт ответил ошибкой (HTTP 429).")

    showcase.fetcher.html = blocked
    with pytest.raises(ValidationError, match="Naver не даёт"):
        showcase.add(admin, "https://naver.me/5T0YL3Hn")
    with pytest.raises(ValidationError, match="Проверьте ссылку"):
        showcase.add(admin, URL)  # other shops: the usual message


def test_page_with_colour_and_size_rows_splits_them():
    # The owner, 20.10.2026: «블랙A 85(XS)» showed as one size.
    import json

    rows = [
        {"uitm1AttrNm": "블랙A", "uitm2AttrNm": "85(XS)", "sumUitmAttrNmStockCnt": 14},
        {"uitm1AttrNm": "그레이시카키B", "uitm2AttrNm": "90(S)", "sumUitmAttrNmStockCnt": 0},
    ]
    data = {"props": {"pageProps": {"itemPtc": {"sellPrc": 129800, "stockList": rows}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    offer = parse_offer(html)
    assert [(s.color, s.name, s.stock, s.available) for s in offer.sizes] == [
        ("블랙A", "85(XS)", 14, True),
        ("그레이시카키B", "90(S)", 0, False),
    ]

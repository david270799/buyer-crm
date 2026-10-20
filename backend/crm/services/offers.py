"""Price and sizes in stock from a shop page («Витрина», the owner, 20.10.2026).

Shops put this data in the page itself in a few known forms; each reader below
takes one of them. Nothing is guessed: what is not found stays empty and the
admin fills it in on the «Подготовка» page.

* Hmall (Next.js): `__NEXT_DATA__` → `itemPtc.sellPrc` and `stockList[]`
  (`uitm1AttrNm`, `sumUitmAttrNmStockCnt`);
* any shop with schema.org JSON-LD `Product.offers` (price, availability);
* Open Graph `product:price:amount`.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from crm.services.link_import import _ld_product, _MetaParser

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_SIZE_NAME = re.compile(r"^(?:XXS|XS|S|M|L|XL|XXL|XXXL|[2-5]XL|F|FREE|\d{2,3}(?:[.,]5)?)$", re.I)
MAX_SIZES = 40


@dataclass(frozen=True)
class SizeStock:
    name: str
    stock: int | None  # None: the shop does not say how many
    available: bool


@dataclass
class Offer:
    price_krw: int | None = None
    sizes: list[SizeStock] = field(default_factory=list)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    if isinstance(value, str):
        digits = re.sub(r"[^\d.]", "", value)
        try:
            number = float(digits)
        except ValueError:
            return None
        return int(number) if number > 0 else None
    return None


def _clean_size(raw: str) -> str:
    name = " ".join(str(raw).split())
    # Hmall writes option values with a one-letter prefix: «AXS», «AM», «A270».
    if len(name) > 1 and name[0] == "A" and _SIZE_NAME.match(name[1:]):
        return name[1:].upper() if name[1:].isalpha() else name[1:]
    return name.upper() if name.isalpha() and len(name) <= 4 else name


def _find(data: Any, key: str) -> Any:
    """The first value of `key` anywhere in nested JSON."""
    stack = [data]
    while stack:
        item = stack.pop(0)
        if isinstance(item, dict):
            if key in item:
                return item[key]
            stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
        elif isinstance(item, list):
            stack.extend(item)
    return None


def _hmall(html: str) -> Offer | None:
    match = _NEXT_DATA.search(html)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return None
    item = _find(data, "itemPtc")
    if not isinstance(item, dict):
        return None
    offer = Offer(price_krw=_int(item.get("sellPrc")))
    for row in item.get("stockList") or []:
        if not isinstance(row, dict) or not row.get("uitm1AttrNm"):
            continue
        stock = row.get("sumUitmAttrNmStockCnt")
        stock = stock if isinstance(stock, int) and not isinstance(stock, bool) else None
        name = _clean_size(row["uitm1AttrNm"])
        if row.get("uitm2AttrNm"):
            name = f"{name} {_clean_size(row['uitm2AttrNm'])}"
        offer.sizes.append(SizeStock(name, stock, (stock or 0) > 0))
    return offer if offer.price_krw or offer.sizes else None


def _json_ld(html: str) -> Offer | None:
    parser = _MetaParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - broken HTML: use what was read
        pass
    product = _ld_product(parser.ld_json)
    offer = Offer()
    offers = product.get("offers") if product else None
    rows = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("@type") == "AggregateOffer":
            offer.price_krw = offer.price_krw or _int(row.get("lowPrice") or row.get("price"))
            continue
        offer.price_krw = offer.price_krw or _int(row.get("price"))
        name = row.get("name") or row.get("size")
        if isinstance(name, str) and _SIZE_NAME.match(_clean_size(name)):
            available = "InStock" in str(row.get("availability", "InStock"))
            offer.sizes.append(SizeStock(_clean_size(name), None, available))
    if offer.price_krw is None:
        offer.price_krw = _int(
            parser.meta.get("product:price:amount") or parser.meta.get("og:price:amount")
        )
    return offer if offer.price_krw or offer.sizes else None


def parse_offer(html: str) -> Offer:
    """Price (KRW) and sizes from a shop page; empty fields when not found."""
    for reader in (_hmall, _json_ld):
        found = reader(html)
        if found is not None:
            found.sizes = found.sizes[:MAX_SIZES]
            return found
    return Offer()


def better_image_url(url: str | None) -> str | None:
    """Shops often give a small preview: ask Hmall for the large picture."""
    if url and "image.hmall.com" in url:
        return re.sub(r"RS=\d+x\d+", "RS=1000x1000", url)
    return url


MAX_PHOTOS = 6
_OG_IMAGE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image|og:image:url|twitter:image)["\'][^>]*>', re.I
)
_CONTENT = re.compile(r'content=["\']([^"\']+)["\']', re.I)
_HMALL_IMAGE = re.compile(r"(https?://image\.hmall\.com/.+?/\d+_)(\d+)(\.jpg)", re.I)


def photo_candidates(html: str, base_url: str, first: str | None) -> list[str]:
    """Product photo URLs in order, best size first; the caller downloads what exists.

    Hmall numbers its photos `…_0.jpg`, `…_1.jpg`… (the page lists only the
    first); other shops give several og:image tags or a JSON-LD image list."""
    from urllib.parse import urljoin

    found: list[str] = []

    def add(url: str | None) -> None:
        if url and url.startswith(("http://", "https://", "//", "/")):
            url = better_image_url(urljoin(base_url, url.replace("&amp;", "&")))
            if url and url not in found:
                found.append(url)

    add(first)
    hmall = _HMALL_IMAGE.match(first or "")
    if hmall:
        prefix, _, ext = hmall.groups()
        for n in range(1, 10):
            add(f"{prefix}{n}{ext}?RS=1000x1000")
        return found
    for tag in _OG_IMAGE.findall(html):
        content = _CONTENT.search(tag)
        add(content.group(1) if content else None)
    parser = _MetaParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        pass
    images = _ld_product(parser.ld_json).get("image")
    for image in images if isinstance(images, list) else [images]:
        add(image.get("url") if isinstance(image, dict) else image)
    return found

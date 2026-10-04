"""«Из ссылки»: fill an order from the shop page (the Mini App's button in the
order form; manual only for now — the owner tests it before it runs on its own).

1. The server opens the link itself (only public http(s) addresses, a size cap,
   a few redirects) and reads what shops publish for previews: Open Graph /
   Twitter tags, JSON-LD `Product`, `<title>`.
2. The page's main photo is downloaded and standardised like any order photo.
3. Gemini gets the photo and those few lines of text (never the whole page)
   and answers brand / model **in English**. Unsure → empty, never invented.

Nothing is saved: the result goes back to the form, the admin saves it.
"""

import ipaddress
import json
import logging
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from crm.domain.errors import ValidationError
from crm.services.common import Actor, require_admin
from crm.services.image_service import ORDER_PHOTOS_FOLDER, ImageService, StoredImage, process_image
from crm.services.recognition import MIN_CONFIDENCE, RecognitionError

logger = logging.getLogger(__name__)

MAX_PAGE_BYTES = 3 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT_SECONDS = 12
# Shops answer browsers; a plain client is often refused.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


class LinkError(Exception):
    """The page could not be read; the message is for the admin (Russian)."""


@dataclass(frozen=True)
class PageInfo:
    title: str | None = None
    description: str | None = None
    brand: str | None = None
    image_url: str | None = None
    site: str | None = None

    @property
    def empty(self) -> bool:
        return not (self.title or self.image_url)


@dataclass(frozen=True)
class LinkImport:
    brand: str | None
    model: str | None
    category: str | None
    title: str | None
    photo: StoredImage | None
    engine: str | None
    note: str | None = None  # what did not work, for the admin


# --- fetching ---------------------------------------------------------------


def _check_public(url: str) -> None:
    """Only public internet addresses: the server must not be pointed at itself."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise LinkError("Ссылка должна начинаться с http:// или https://.")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or None, proto=socket.IPPROTO_TCP)
    except OSError:
        raise LinkError("Сайт не найден — проверьте ссылку.") from None
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise LinkError("Эту ссылку открыть нельзя (внутренний адрес).")


def _get(client: httpx.Client, url: str, limit: int) -> tuple[bytes, str, str]:
    """GET with checked redirects and a size cap → (body, content type, final URL)."""
    for _ in range(MAX_REDIRECTS + 1):
        _check_public(url)
        with client.stream("GET", url, headers=_HEADERS) as response:
            if response.is_redirect and response.headers.get("location"):
                url = urljoin(url, response.headers["location"])
                continue
            if response.status_code != 200:
                raise LinkError(f"Сайт ответил ошибкой (HTTP {response.status_code}).")
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > limit:
                    raise LinkError("Страница слишком большая.")
            return bytes(body), response.headers.get("content-type", ""), url
    raise LinkError("Слишком много переадресаций.")


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.ld_json: list[str] = []
        self._in_title = False
        self._in_ld = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"]
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and "ld+json" in a.get("type", ""):
            self._in_ld = True
            self.ld_json.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._in_ld:
            self.ld_json[-1] += data


def _ld_product(blocks: list[str]) -> dict[str, Any]:
    """The first schema.org Product in the JSON-LD blocks."""
    stack: list[Any] = []
    for block in blocks:
        try:
            stack.append(json.loads(block))
        except ValueError:
            continue
    while stack:
        item = stack.pop(0)
        if isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            kind = item.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if "Product" in kinds:
                return item
            stack.extend(v for v in item.values() if isinstance(v, (list, dict)))
    return {}


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, dict):
            value = value.get("name")
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:300]
    return None


def parse_page(html: str, base_url: str) -> PageInfo:
    parser = _MetaParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - broken HTML: use what was read
        pass
    meta, product = parser.meta, _ld_product(parser.ld_json)
    image = _first_text(
        product.get("image"),
        meta.get("og:image"),
        meta.get("og:image:url"),
        meta.get("twitter:image"),
    )
    return PageInfo(
        title=_first_text(
            product.get("name"), meta.get("og:title"), meta.get("twitter:title"), parser.title
        ),
        description=_first_text(product.get("description"), meta.get("og:description")),
        brand=_first_text(product.get("brand"), meta.get("product:brand")),
        image_url=urljoin(base_url, image) if image else None,
        site=_first_text(meta.get("og:site_name")) or urlsplit(base_url).hostname,
    )


class PageFetcher:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)

    def page(self, url: str) -> PageInfo:
        try:
            body, kind, final = _get(self._client, url, MAX_PAGE_BYTES)
        except httpx.HTTPError as exc:
            raise LinkError(f"Сайт не открылся ({type(exc).__name__}).") from None
        if "html" not in kind and not body.lstrip()[:20].lower().startswith(
            (b"<!doctype", b"<html")
        ):
            raise LinkError("По ссылке не страница магазина.")
        return parse_page(body.decode("utf-8", errors="replace"), final)

    def image(self, url: str) -> bytes:
        try:
            body, _, _ = _get(self._client, url, MAX_IMAGE_BYTES)
        except httpx.HTTPError as exc:
            raise LinkError(f"Фото с сайта не загрузилось ({type(exc).__name__}).") from None
        return body


# --- the service ------------------------------------------------------------


def _page_text(page: PageInfo) -> str:
    lines = [
        f"Site: {page.site}" if page.site else "",
        f"Title: {page.title}" if page.title else "",
        f"Brand: {page.brand}" if page.brand else "",
        f"Description: {page.description}" if page.description else "",
    ]
    return "\n".join(line for line in lines if line)


class LinkImportService:
    def __init__(self, images: ImageService | None, recognizer: Any, fetcher: Any = None):
        self._images = images
        self._recognizer = recognizer  # GeminiRecognizer (read_listing) or None
        self._fetcher = fetcher or PageFetcher()

    def import_link(self, actor: Actor, url: str) -> LinkImport:
        require_admin(actor)
        url = (url or "").strip()
        if not url:
            raise ValidationError("Сначала впишите ссылку на товар.")
        try:
            page = self._fetcher.page(url)
        except LinkError as exc:
            raise ValidationError(f"{exc} Заполните вручную.") from None
        if page.empty:
            raise ValidationError(
                "Магазин не отдал название и фото товара (сайт закрыт для ботов). "
                "Заполните вручную."
            )
        notes: list[str] = []
        image: bytes | None = None
        photo: StoredImage | None = None
        if page.image_url:
            try:
                main, thumb, size = process_image(self._fetcher.image(page.image_url))
                image = main
                if self._images is not None:
                    photo = self._images.store_processed(
                        main, thumb, size, folder=ORDER_PHOTOS_FOLDER
                    )
            except (LinkError, ValidationError) as exc:
                notes.append(f"фото: {exc}")
        else:
            notes.append("на странице нет фото товара")

        brand, model, category, engine = page.brand, page.title, None, None
        if self._recognizer is not None and hasattr(self._recognizer, "read_listing"):
            try:
                answer = self._recognizer.read_listing(image, _page_text(page))
                engine = self._recognizer.engine
                sure = answer.get("confidence", 0) >= MIN_CONFIDENCE
                brand = answer.get("brand") if sure else None
                model = answer.get("model") if sure else None
                category = answer.get("category")
                if not sure:
                    notes.append("Gemini не уверен в названии")
            except RecognitionError as exc:
                notes.append(f"Gemini: {exc}")
        elif self._recognizer is None:
            notes.append("Gemini не подключён — название как на сайте")
        logger.info(
            "Link import %s: brand=%s model=%s photo=%s", page.site, brand, model, bool(photo)
        )
        return LinkImport(
            brand=brand,
            model=model,
            category=category,
            title=page.title,
            photo=photo,
            engine=engine,
            note="; ".join(notes) or None,
        )

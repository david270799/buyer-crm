"""«Витрина» (the owner, 20.10.2026; test mode — only the admin sees it).

The admin sends a shop link → a draft card (photo, English name, shop price,
sizes in stock). On «Подготовка» he checks it, sets the markup or the client
price by hand and publishes it. On the «Витрина» a size is chosen and «Заказать»
makes an ordinary new order («Из витрины»: the link, the shop and the price are
filled in). No money moves: the order is bought out as usual with /buy.
"""

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from crm.domain.categories import CATEGORIES, category_from_text
from crm.domain.enums import Role
from crm.domain.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from crm.domain.models import ShowcaseItem
from crm.repositories import ShowcaseRepository
from crm.services.common import Actor, Auditor, Clock, require_admin
from crm.services.image_service import ImageService, process_image, process_showcase_image
from crm.services.link_import import (
    _TRANSLATE_AGAIN,
    LinkError,
    PageFetcher,
    _page_text,
    has_hangul,
    parse_page,
)
from crm.services.offers import (
    MAX_PHOTOS,
    Offer,
    hmall_option_urls,
    is_plain_size,
    parse_hmall_options,
    parse_offer,
    photo_candidates,
)
from crm.services.order_service import NewOrder, OrderService, clean_shop
from crm.services.recognition import MIN_CONFIDENCE, RecognitionError
from crm.services.sizes import order_sizes
from crm.storage import Database, Transaction

logger = logging.getLogger(__name__)

SHOWCASE_PHOTOS_FOLDER = "showcase"
MAX_PRICE_KRW = 50_000_000
MAX_MARKUP_PCT = 300
MAX_CART = 20

# Host → the shop's name as in the «Магазин» bubbles.
_SHOP_NAMES = {
    "hmall.com": "Hmall",
    "musinsa.com": "Musinsa",
    "29cm.co.kr": "29CM",
    "nike.com": "Nike",
    "adidas.co.kr": "Adidas",
    "on.com": "On",
    "ssg.com": "SSG.com",
    "gmarket.co.kr": "G-Market",
    "coupang.com": "Coupang",
    "lotteimall.com": "Lotte Home Shopping",
    "shinsegaemall.ssg.com": "Shinsegae Mall",
    "cjonstyle.com": "CJ OnStyle",
    "kream.co.kr": "KREAM",
}


# Naver Smart Store answers every program with HTTP 429 (checked 20.10.2026,
# also from the owner's Korean server), so say so plainly.
NAVER_BLOCKED = (
    "Naver не даёт программам читать страницы Smart Store. "
    "Такой товар пока можно добавить только вручную (обычным заказом)."
)


def _is_naver(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "naver.me" or host.endswith((".naver.com", ".naver.me")) or host == "naver.com"


def _gateway_target(url: str) -> str | None:
    """SSG share links (ssg.li) open a «snsGateway» page that only points to the
    product (`?url=…`); the product page is that inner URL."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not (host == "ssg.com" or host.endswith(".ssg.com")) or "snsGateway" not in parts.path:
        return None
    inner = (parse_qs(parts.query).get("url") or [""])[0]
    inner_host = (urlsplit(inner).hostname or "").lower()
    ssg = inner_host == "ssg.com" or inner_host.endswith(".ssg.com")
    return inner if inner.startswith("https://") and ssg else None


def _require_viewer(actor: Actor) -> None:
    """The showcase is for the admin and the client (not the client's helpers)."""
    if actor.role not in (Role.ADMIN, Role.CLIENT):
        raise PermissionDeniedError("Витрина доступна только клиенту.")


def shop_name(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.").removeprefix("m.")
    for domain, name in _SHOP_NAMES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host or None


def _price(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= MAX_PRICE_KRW:
        raise ValidationError(f"«{name}» — число от 1 до {MAX_PRICE_KRW:,} ₩.")
    return value


def _sizes(offer: Offer) -> list[dict[str, Any]]:
    rows = []
    for s in offer.sizes:
        row = {"name": s.name, "stock": s.stock, "available": s.available}
        if s.color:
            row["color"] = s.color
        rows.append(row)
    return rows


@dataclass(frozen=True)
class CartLine:
    item_id: str
    size: str | None
    color: str | None = None  # products chosen colour first, then size


# Shop pages read at the same time (each one downloads up to MAX_PHOTOS photos
# and resizes them): the server has 1 GB RAM, so a burst of links waits here
# in turn instead of decoding dozens of photos at once.
READ_PARALLEL = 2
CLIENT_REFRESH_EVERY = timedelta(minutes=1)  # the shop is not asked more often
HISTORY_LIMIT = 300  # newest entries shown in «Статистика»


class ShowcaseService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        repo: ShowcaseRepository,
        orders: OrderService,
        auditor: Auditor,
        images: ImageService | None,
        recognizer: Any = None,
        fetcher: Any = None,
    ):
        self._db = db
        self._clock = clock
        self._repo = repo
        self._orders = orders
        self._auditor = auditor
        self._images = images
        self._recognizer = recognizer
        self._fetcher = fetcher or PageFetcher()
        self._reading = threading.BoundedSemaphore(READ_PARALLEL)

    # --- reading the shop page -----------------------------------------------

    def _offer(self, html: str) -> Offer:
        """Price and sizes; Hmall's colour → size products ask Hmall for the
        pairs (a failed answer keeps what the page itself showed)."""
        offer = parse_offer(html)
        urls = hmall_option_urls(html)
        if urls and hasattr(self._fetcher, "json"):
            try:
                pairs = parse_hmall_options(*(self._fetcher.json(u) for u in urls))
            except LinkError as exc:
                logger.info("Hmall options not read: %s", exc)
                pairs = None
            if pairs:
                offer.sizes = pairs
        return offer

    def _split(self, rows: list[dict[str, Any]]) -> None:
        """«블랙A 85(XS)» in one name → colour «블랙A» + size «85(XS)» (the owner,
        20.10.2026: Gemini splits, the card asks colour first). Applied only
        when every option splits and both parts are in the name word for word."""
        if not rows or any(r.get("color") for r in rows):
            return
        names = [r["name"] for r in rows]
        if all(is_plain_size(n) for n in names):
            return
        if self._recognizer is None or not hasattr(self._recognizer, "split_options"):
            return
        try:
            parts = self._recognizer.split_options(names)
        except RecognitionError as exc:
            logger.info("Option names not split: %s", exc)
            return

        def squeeze(text: str) -> str:
            return "".join(text.split()).lower()

        for name, (color, size) in zip(names, parts, strict=True):
            whole = squeeze(name)
            if not color or not size or squeeze(color) not in whole or squeeze(size) not in whole:
                return  # one doubtful answer: keep the shop's names as they are
        for row, (color, size) in zip(rows, parts, strict=True):
            row["color"], row["name"] = color, size

    def _translate(self, rows: list[dict[str, Any]], known: dict[str, str]) -> None:
        """Korean colour / size names get an English name in front, the shop's
        own word kept in brackets: «Black A (블랙A)» (the owner, 20.10.2026).
        `known`: names already translated on this card (no new Gemini call)."""
        korean = sorted(
            {r[k] for r in rows for k in ("color", "name") if has_hangul(r.get(k))} - set(known)
        )
        found = dict(known)
        can = self._recognizer is not None and hasattr(self._recognizer, "translate_labels")
        if korean and can:
            try:
                for ko, en in zip(korean, self._recognizer.translate_labels(korean), strict=True):
                    if en:
                        found[ko] = f"{en} ({ko})"
            except RecognitionError as exc:
                logger.info("Option names not translated: %s", exc)
        for row in rows:
            for key in ("color", "name"):
                if row.get(key) in found:
                    row[f"{key}_ko"] = row[key]
                    row[key] = found[row[key]]

    def _read(self, url: str) -> tuple[dict[str, Any], list[str]]:
        """Fields from the shop page and what could not be read."""
        with self._reading:
            return self._read_page(url)

    def _read_page(self, url: str) -> tuple[dict[str, Any], list[str]]:
        try:
            html, final = self._fetcher.html(url)
            inner = _gateway_target(final)
            if inner:
                html, final = self._fetcher.html(inner)
        except LinkError as exc:
            if "HTTP 429" in str(exc) and _is_naver(url):
                raise ValidationError(NAVER_BLOCKED) from None
            raise ValidationError(f"{exc} Проверьте ссылку.") from None
        page = parse_page(html, final)
        offer = self._offer(html)
        notes: list[str] = []
        fields: dict[str, Any] = {
            "title": page.title,
            "shop_price_krw": offer.price_krw,
            "sizes": _sizes(offer),
        }
        self._split(fields["sizes"])
        self._translate(fields["sizes"], {})
        if not offer.price_krw:
            notes.append("цена не найдена")
        if not offer.sizes:
            notes.append("размеры не найдены")
        image, photos = None, []
        for photo_url in photo_candidates(html, final, page.image_url):
            if len(photos) >= MAX_PHOTOS:
                break
            try:
                original = self._fetcher.image(photo_url)
            except (LinkError, ValidationError):
                if photos and "image.hmall.com" in photo_url:
                    break  # Hmall numbers photos in a row: the first gap is the end
                continue
            try:
                if image is None:
                    image, _, _ = process_image(original)  # small WebP for Gemini
                if self._images is not None:
                    main, thumb, size = process_showcase_image(original)
                    stored = self._images.store_processed(
                        main, thumb, size, folder=SHOWCASE_PHOTOS_FOLDER, jpeg=True
                    )
                    photos.append(
                        {"photo_url": stored.photo_url, "thumbnail_url": stored.thumbnail_url}
                    )
            except ValidationError as exc:
                notes.append(f"фото: {exc}")
        if photos:
            fields["photos"] = photos
            fields["photo_url"] = photos[0]["photo_url"]
            fields["thumbnail_url"] = photos[0]["thumbnail_url"]
        elif image is None:
            notes.append("нет фото")
        brand = page.brand if not has_hangul(page.brand) else None
        model = page.title if not has_hangul(page.title) else None
        category = None
        if self._recognizer is not None and hasattr(self._recognizer, "read_listing"):
            try:
                answer = self._recognizer.read_listing(image, _page_text(page))
                if has_hangul(answer.get("brand")) or has_hangul(answer.get("model")):
                    answer = self._recognizer.read_listing(
                        image, _page_text(page) + _TRANSLATE_AGAIN
                    )
                if answer.get("confidence", 0) >= MIN_CONFIDENCE:
                    brand, model = answer.get("brand"), answer.get("model")
                category = category_from_text(answer.get("category"))
            except RecognitionError as exc:
                notes.append(f"Gemini: {exc}")
        fields["brand"] = None if has_hangul(brand) else brand
        fields["model"] = None if has_hangul(model) else model
        fields["category"] = category
        if not (fields["brand"] or fields["model"]):
            notes.append("название не переведено")
        price, official_url, note = self._official(fields["brand"], fields["model"])
        if price:
            fields["official_price_krw"], fields["official_url"] = price, official_url
        elif note:
            notes.append(note)
        return fields, notes

    def page_source(self, actor: Actor, url: str) -> tuple[str, str]:
        """/pagefile: the shop page exactly as this server gets it (HTML, final
        URL) — to see whether a shop lets the server in and how its page is
        built before teaching the CRM to read it (the owner, 20.10.2026: SSG)."""
        require_admin(actor)
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValidationError("Нужна ссылка (https://…).")
        try:
            with self._reading:
                html, final = self._fetcher.html(url)
                inner = _gateway_target(final)
                if inner:
                    html, final = self._fetcher.html(inner)
        except LinkError as exc:
            raise ValidationError(f"Магазин не пустил сервер: {exc}") from None
        return html, final

    # --- admin: drafts ------------------------------------------------------

    def add(self, actor: Actor, url: str) -> ShowcaseItem:
        require_admin(actor)
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValidationError("Нужна ссылка на товар (https://…).")
        fields, notes = self._read(url)
        item_id = f"sc{self._db.new_id()}"

        def fn(tx: Transaction) -> None:
            now = self._clock.now()
            self._repo.create(
                tx,
                item_id,
                {
                    **fields,
                    "url": url,
                    "shop": shop_name(url),
                    "status": "draft",
                    "markup_type": "krw",
                    "markup_value": 0,
                    "note": "; ".join(notes) or None,
                    "refreshed_at": now,
                    "created_at": now,
                    "updated_at": now,
                    "created_by": actor.id,
                },
            )
            self._auditor.record(
                tx,
                actor,
                now,
                action="showcase.add",
                entity_type="showcase",
                entity_id=item_id,
                before=None,
                after={"url": url, "price": fields.get("shop_price_krw")},
            )

        self._db.run_transaction(fn)
        return self.get(actor, item_id)

    def find_official(self, actor: Actor, item_id: str) -> ShowcaseItem:
        """Look for the brand's own store price (Gemini + Google Search). Taken
        only when the page is on a domain carrying the brand's name."""
        require_admin(actor)
        item = self.get(actor, item_id)
        price, url, note = self._official(item.brand, item.model or item.title)
        fields: dict[str, Any] = {"note": note} if note else {}
        if price:
            fields.update(official_price_krw=price, official_url=url)
        if not fields:
            fields["official_url"] = None
        return self._write(actor, item_id, fields, "showcase.official")

    def _official(
        self, brand: str | None, model: str | None
    ) -> tuple[int | None, str | None, str | None]:
        if not brand or self._recognizer is None:
            return None, None, None
        if not hasattr(self._recognizer, "find_official_price"):
            return None, None, None
        try:
            answer = self._recognizer.find_official_price(f"{brand} {model or ''}".strip())
        except RecognitionError as exc:
            return None, None, f"официальная цена: {exc}"
        url, price = answer.get("url"), answer.get("price_krw")
        token = "".join(ch for ch in brand.lower() if ch.isalnum())
        host = (urlsplit(url).hostname or "").lower() if url else ""
        if not price or not token or token not in host.replace("-", ""):
            return None, None, "официальная цена не найдена"
        return price, url, None

    def get(self, actor: Actor, item_id: str) -> ShowcaseItem:
        """Any card for the admin; the client sees only published ones."""
        _require_viewer(actor)
        item = self._repo.get(self._db, item_id)
        if item is None or (actor.role is not Role.ADMIN and item.status != "published"):
            raise NotFoundError("Карточка не найдена.")
        return item

    def items(self, actor: Actor, status: str | None = None) -> list[ShowcaseItem]:
        _require_viewer(actor)
        if actor.role is not Role.ADMIN:
            status = "published"
        items = self._repo.list_all(self._db)
        if status:
            items = [i for i in items if i.status == status]
        newest = datetime.min
        items.sort(
            key=lambda i: (i.published_at or i.created_at or newest).replace(tzinfo=None),
            reverse=True,
        )
        return items

    def update(self, actor: Actor, item_id: str, changes: dict[str, Any]) -> ShowcaseItem:
        """Prices, markup and names from «Подготовка» (only the given fields)."""
        require_admin(actor)
        fields: dict[str, Any] = {}
        for name in ("shop_price_krw", "official_price_krw", "client_price_override"):
            if name in changes:
                fields[name] = _price(changes[name], "Цена")
        if "markup_type" in changes:
            if changes["markup_type"] not in ("krw", "pct"):
                raise ValidationError("Наценка: «+ ₩» или «%».")
            fields["markup_type"] = changes["markup_type"]
        if "markup_value" in changes:
            value = changes["markup_value"]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValidationError("Наценка — число от 0.")
            fields["markup_value"] = value
        for name, limit in (("brand", 60), ("model", 120)):
            if name in changes:
                text = (changes[name] or "").strip() or None
                if text and len(text) > limit:
                    raise ValidationError(f"Слишком длинное поле ({limit} символов).")
                fields[name] = text
        if "shop" in changes:
            fields["shop"] = clean_shop(changes["shop"])
        if "category" in changes:
            if changes["category"] not in (None, *CATEGORIES):
                raise ValidationError("Неизвестная категория.")
            fields["category"] = changes["category"]
        if not fields:
            raise ValidationError("Нет изменений.")
        current = self.get(actor, item_id)
        kind = fields.get("markup_type", current.markup_type)
        if kind == "pct" and fields.get("markup_value", current.markup_value) > MAX_MARKUP_PCT:
            raise ValidationError(f"Наценка не больше {MAX_MARKUP_PCT}%.")
        return self._write(actor, item_id, fields, "showcase.update")

    def refresh(self, actor: Actor, item_id: str) -> ShowcaseItem:
        """Read the shop page again: the price and the sizes in stock now.
        The client may press «Обновить» too (the owner, 20.10.2026): a card
        read less than CLIENT_REFRESH_EVERY ago is just returned as it is."""
        item = self.get(actor, item_id)
        if actor.role is not Role.ADMIN and item.refreshed_at is not None:
            if self._clock.now() - item.refreshed_at < CLIENT_REFRESH_EVERY:
                return item
        try:
            with self._reading:
                html, _ = self._fetcher.html(item.url)
        except LinkError as exc:
            raise ValidationError(f"Магазин не открылся: {exc}") from None
        offer = self._offer(html)
        fields: dict[str, Any] = {"refreshed_at": self._clock.now()}
        if offer.sizes:
            known = {
                r[f"{k}_ko"]: r[k]
                for r in item.sizes
                for k in ("color", "name")
                if r.get(f"{k}_ko")
            }
            fields["sizes"] = _sizes(offer)
            self._split(fields["sizes"])
            self._translate(fields["sizes"], known)
        if offer.price_krw:
            fields["shop_price_krw"] = offer.price_krw
        return self._write(actor, item_id, fields, "showcase.refresh")

    def set_status(self, actor: Actor, item_id: str, status: str) -> ShowcaseItem:
        if status not in ("draft", "published", "hidden"):
            raise ValidationError("Неизвестный статус карточки.")
        require_admin(actor)
        item = self.get(actor, item_id)
        if status == "published" and not item.client_price_krw:
            raise ConflictError("Сначала укажите цену: в магазине или для клиента.")
        fields: dict[str, Any] = {"status": status}
        if status == "published":
            fields["published_at"] = self._clock.now()
        return self._write(actor, item_id, fields, f"showcase.{status}")

    def delete(self, actor: Actor, item_id: str) -> None:
        require_admin(actor)
        self.get(actor, item_id)

        def fn(tx: Transaction) -> None:
            now = self._clock.now()
            self._repo.delete(tx, item_id)
            self._auditor.record(
                tx,
                actor,
                now,
                action="showcase.delete",
                entity_type="showcase",
                entity_id=item_id,
                before=None,
                after=None,
            )

        self._db.run_transaction(fn)

    def _write(
        self, actor: Actor, item_id: str, fields: dict[str, Any], action: str
    ) -> ShowcaseItem:
        def fn(tx: Transaction) -> None:
            if self._repo.get(tx, item_id) is None:
                raise NotFoundError("Карточка не найдена.")
            now = self._clock.now()
            self._repo.update(tx, item_id, {**fields, "updated_at": now})
            after = {
                k: v for k, v in fields.items() if k != "sizes" and not isinstance(v, datetime)
            }
            self._auditor.record(
                tx,
                actor,
                now,
                action=action,
                entity_type="showcase",
                entity_id=item_id,
                before=None,
                after=after,
            )

        self._db.run_transaction(fn)
        return self.get(actor, item_id)

    # --- interest («Статистика» in «Настройки», the owner, 20.10.2026) -------------

    def viewed(self, actor: Actor, item_id: str) -> None:
        """The viewer opened a card: counted per card and kept in the history."""
        self.get(actor, item_id)

        def fn(tx: Transaction) -> None:
            stats = self._repo.get_stats(tx, actor.id)
            views = dict(stats.get("views") or {})
            views[item_id] = int(views.get(item_id, 0)) + 1
            now = self._clock.now()
            last = {**(stats.get("last") or {}), item_id: now}
            self._repo.set_stats(
                tx,
                actor.id,
                {
                    "views": views,
                    "last": last,
                    "last_at": now,
                    "first_at": stats.get("first_at") or now,
                },
            )
            self._log(tx, actor, item_id, "view", now)

        self._db.run_transaction(fn)

    def _log(self, tx: Transaction, actor: Actor, item_id: str, kind: str, at: datetime) -> None:
        entry = {"viewer": actor.id, "item_id": item_id, "kind": kind, "at": at}
        self._repo.add_log(tx, f"log{self._db.new_id()}", entry)

    def statistics(self, actor: Actor) -> dict[str, Any]:
        """«Статистика» (the owner, 20.10.2026): per viewer and card how often
        it was opened and whether it is ♥, the orders, and the history of
        opens / ♥ / orders, newest first (the page filters and adds them up)."""
        require_admin(actor)
        items = {
            i.id: {"title": i.title_line, "thumbnail_url": i.thumbnail_url or i.photo_url}
            for i in self._repo.list_all(self._db)
        }
        likes = {viewer: data.get("ids") or [] for viewer, data in self._repo.all_likes(self._db)}
        cards = []
        for viewer, data in self._repo.all_stats(self._db):
            last = data.get("last") or {}
            for item_id, count in (data.get("views") or {}).items():
                cards.append(
                    {
                        "viewer": viewer,
                        "item_id": item_id,
                        "views": int(count),
                        "liked": item_id in likes.get(viewer, []),
                        "last_at": last.get(item_id),
                    }
                )
        seen = {(c["viewer"], c["item_id"]) for c in cards}
        for viewer, ids in likes.items():  # ♥ without a counted open (older data)
            for item_id in ids:
                if (viewer, item_id) not in seen and item_id in items:
                    cards.append(
                        {
                            "viewer": viewer,
                            "item_id": item_id,
                            "views": 0,
                            "liked": True,
                            "last_at": None,
                        }
                    )
        history = [
            {
                "kind": d.get("kind"),
                "viewer": d.get("viewer"),
                "item_id": d.get("item_id"),
                "at": d.get("at"),
            }
            for _, d in self._repo.all_log(self._db)
        ]
        for order in self._orders.showcase_orders(actor):
            history.append(
                {
                    "kind": "order",
                    "viewer": order.created_by,
                    "item_id": order.showcase_id,
                    "at": order.timestamp("created_at"),
                    "order_id": order.id,
                    "size": order.size or order.size_kr,
                }
            )
        history.sort(key=lambda h: h["at"] or datetime.min.replace(tzinfo=UTC), reverse=True)
        return {"items": items, "cards": cards, "history": history[:HISTORY_LIMIT]}

    # --- likes and orders -----------------------------------------------------

    def liked(self, actor: Actor) -> list[str]:
        _require_viewer(actor)
        return self._repo.liked(self._db, actor.id)

    def toggle_like(self, actor: Actor, item_id: str) -> list[str]:
        self.get(actor, item_id)

        def fn(tx: Transaction) -> list[str]:
            ids = self._repo.liked(tx, actor.id)
            liked = item_id not in ids
            ids = [item_id, *ids] if liked else [i for i in ids if i != item_id]
            self._repo.set_liked(tx, actor.id, ids[:200])
            self._log(tx, actor, item_id, "like" if liked else "unlike", self._clock.now())
            return ids

        return self._db.run_transaction(fn)

    def order(self, actor: Actor, lines: list[CartLine]):
        """«Заказать»: one new order per cart line (no money moves)."""
        _require_viewer(actor)
        if not lines:
            raise ValidationError("Корзина пуста.")
        if len(lines) > MAX_CART:
            raise ValidationError(f"Не больше {MAX_CART} товаров за раз.")
        items = {}
        for line in lines:
            item = self.get(actor, line.item_id)
            if item.status != "published":
                raise ConflictError(f"«{item.title_line}» снят с витрины.")
            colors = {s.get("color") for s in item.sizes if s.get("color")}
            if colors and line.color not in colors:
                raise ValidationError(f"Выберите цвет для «{item.title_line}».")
            names = {
                s.get("name") for s in item.sizes if not colors or s.get("color") == line.color
            }
            if item.sizes and line.size not in names:
                raise ValidationError(f"Выберите размер для «{item.title_line}».")
            items[line.item_id] = item
        created = []
        for line in lines:
            item = items[line.item_id]
            size, size_kr = order_sizes(line.size, None, from_caption=False)
            created.append(
                self._orders.create_showcase_order(
                    actor,
                    NewOrder(
                        brand=item.brand,
                        model=" · ".join(p for p in (item.model, line.color) if p) or None,
                        size=size,
                        size_kr=size_kr,
                        source_url=item.url,
                        shop=item.shop,
                        category=item.category,
                        client_price=item.client_price_krw,
                        photo_url=item.photo_url,
                        thumbnail_url=item.thumbnail_url,
                        internal_comment=(
                            f"Из витрины · цена магазина ₩ {item.shop_price_krw:,}"
                            if item.shop_price_krw
                            else "Из витрины"
                        ),
                        showcase_id=item.id,
                    ),
                )
            )
        return created

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
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from crm.domain.categories import CATEGORIES, category_from_text
from crm.domain.errors import ConflictError, NotFoundError, ValidationError
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
from crm.services.offers import MAX_PHOTOS, Offer, parse_offer, photo_candidates
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
    return [{"name": s.name, "stock": s.stock, "available": s.available} for s in offer.sizes]


@dataclass(frozen=True)
class CartLine:
    item_id: str
    size: str | None


# Shop pages read at the same time (each one downloads up to MAX_PHOTOS photos
# and resizes them): the server has 1 GB RAM, so a burst of links waits here
# in turn instead of decoding dozens of photos at once.
READ_PARALLEL = 2


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

    def _read(self, url: str) -> tuple[dict[str, Any], list[str]]:
        """Fields from the shop page and what could not be read."""
        with self._reading:
            return self._read_page(url)

    def _read_page(self, url: str) -> tuple[dict[str, Any], list[str]]:
        try:
            html, final = self._fetcher.html(url)
        except LinkError as exc:
            raise ValidationError(f"{exc} Проверьте ссылку.") from None
        page = parse_page(html, final)
        offer = parse_offer(html)
        notes: list[str] = []
        fields: dict[str, Any] = {
            "title": page.title,
            "shop_price_krw": offer.price_krw,
            "sizes": _sizes(offer),
        }
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
        require_admin(actor)
        item = self._repo.get(self._db, item_id)
        if item is None:
            raise NotFoundError("Карточка не найдена.")
        return item

    def items(self, actor: Actor, status: str | None = None) -> list[ShowcaseItem]:
        require_admin(actor)
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
        """Read the shop page again: the price and the sizes in stock now."""
        item = self.get(actor, item_id)
        try:
            html, _ = self._fetcher.html(item.url)
        except LinkError as exc:
            raise ValidationError(f"Магазин не открылся: {exc}") from None
        offer = parse_offer(html)
        fields: dict[str, Any] = {"refreshed_at": self._clock.now()}
        if offer.sizes:
            fields["sizes"] = _sizes(offer)
        if offer.price_krw:
            fields["shop_price_krw"] = offer.price_krw
        return self._write(actor, item_id, fields, "showcase.refresh")

    def set_status(self, actor: Actor, item_id: str, status: str) -> ShowcaseItem:
        if status not in ("draft", "published", "hidden"):
            raise ValidationError("Неизвестный статус карточки.")
        item = self.get(actor, item_id)
        if status == "published" and not item.client_price_krw:
            raise ConflictError("Сначала укажите цену: в магазине или для клиента.")
        fields: dict[str, Any] = {"status": status}
        if status == "published":
            fields["published_at"] = self._clock.now()
        return self._write(actor, item_id, fields, f"showcase.{status}")

    def delete(self, actor: Actor, item_id: str) -> None:
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
        """The viewer opened a card: counted per card for the statistics."""
        self.get(actor, item_id)

        def fn(tx: Transaction) -> None:
            stats = self._repo.get_stats(tx, actor.id)
            views = dict(stats.get("views") or {})
            views[item_id] = int(views.get(item_id, 0)) + 1
            now = self._clock.now()
            self._repo.set_stats(
                tx,
                actor.id,
                {"views": views, "last_at": now, "first_at": stats.get("first_at") or now},
            )

        self._db.run_transaction(fn)

    def statistics(self, actor: Actor) -> list[dict[str, Any]]:
        """Per viewer: cards opened, opens, likes, orders, the most opened cards."""
        require_admin(actor)
        items = {i.id: i for i in self._repo.list_all(self._db)}
        likes = {viewer: data.get("ids") or [] for viewer, data in self._repo.all_likes(self._db)}
        stats = dict(self._repo.all_stats(self._db))
        orders: dict[str, int] = {}
        for order in self._orders.showcase_orders(actor):
            orders[order.created_by or ""] = orders.get(order.created_by or "", 0) + 1
        result = []
        for viewer in sorted(set(stats) | set(likes)):
            views = {k: int(v) for k, v in (stats.get(viewer, {}).get("views") or {}).items()}
            liked = [i for i in likes.get(viewer, []) if i in items]
            top = sorted(views.items(), key=lambda kv: kv[1], reverse=True)[:5]
            result.append(
                {
                    "viewer": viewer,
                    "cards_opened": len(views),
                    "opens": sum(views.values()),
                    "likes": len(liked),
                    "orders": orders.get(viewer, 0),
                    "last_at": stats.get(viewer, {}).get("last_at"),
                    "top": [
                        {
                            "id": item_id,
                            "title": items[item_id].title_line if item_id in items else "удалена",
                            "opens": count,
                            "liked": item_id in liked,
                        }
                        for item_id, count in top
                    ],
                    "liked": [
                        {
                            "id": i,
                            "title": items[i].title_line,
                            "opens": views.get(i, 0),
                            "liked": True,
                        }
                        for i in liked[:10]
                    ],
                }
            )
        return result

    # --- likes and orders -----------------------------------------------------

    def liked(self, actor: Actor) -> list[str]:
        require_admin(actor)
        return self._repo.liked(self._db, actor.id)

    def toggle_like(self, actor: Actor, item_id: str) -> list[str]:
        self.get(actor, item_id)

        def fn(tx: Transaction) -> list[str]:
            ids = self._repo.liked(tx, actor.id)
            ids = [i for i in ids if i != item_id] if item_id in ids else [item_id, *ids]
            self._repo.set_liked(tx, actor.id, ids[:200])
            return ids

        return self._db.run_transaction(fn)

    def order(self, actor: Actor, lines: list[CartLine]):
        """«Заказать»: one new order per cart line (no money moves)."""
        require_admin(actor)
        if not lines:
            raise ValidationError("Корзина пуста.")
        if len(lines) > MAX_CART:
            raise ValidationError(f"Не больше {MAX_CART} товаров за раз.")
        items = {}
        for line in lines:
            item = self.get(actor, line.item_id)
            if item.status != "published":
                raise ConflictError(f"«{item.title_line}» снят с витрины.")
            names = {s.get("name") for s in item.sizes}
            if item.sizes and line.size not in names:
                raise ValidationError(f"Выберите размер для «{item.title_line}».")
            items[line.item_id] = item
        created = []
        for line in lines:
            item = items[line.item_id]
            size, size_kr = order_sizes(line.size, None, from_caption=False)
            created.append(
                self._orders.create_order(
                    actor,
                    NewOrder(
                        brand=item.brand,
                        model=item.model,
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

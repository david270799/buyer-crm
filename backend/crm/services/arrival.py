"""«Пришло на склад» (the owner, 16.10.2026): the admin sends a photo of the item
that arrived (label, size tag, box). Gemini compares the size on the photo with
the ordered size (not for watches) and writes a short Korean review for the shop's
review points. The photo and the result are saved on the order (admin only) and a
«Выкуплен» order becomes «На складе». No money moves.
"""

import logging
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from crm.domain.enums import OrderStatus
from crm.domain.errors import ConflictError, NotFoundError
from crm.domain.ids import normalize_order_id
from crm.domain.models import Order
from crm.repositories import OrderRepository
from crm.services.common import Actor, Auditor, Clock, require_admin
from crm.services.recognition import MIN_CONFIDENCE, RecognitionError
from crm.storage import Database, Transaction

logger = logging.getLogger(__name__)

MATCH = "match"
MISMATCH = "mismatch"
UNCLEAR = "unclear"  # the size on the photo could not be read for sure
SKIPPED = "skipped"  # watches, no ordered size, or Gemini is not connected


def _norm(size: str | None) -> str:
    return "".join((size or "").casefold().split()).removesuffix("mm")


def ordered_sizes(order: Order) -> list[str]:
    """The ordered size and its Korean version (e.g. «L» and «100», «42» and «265»)."""
    return [s for s in (order.size, order.size_kr) if s]


def judge(order: Order, answer: dict[str, Any] | None) -> str:
    sizes = ordered_sizes(order)
    if order.category == "watch" or not sizes or answer is None:
        return SKIPPED
    seen = answer.get("size_seen")
    if not seen:
        return UNCLEAR
    if any(_norm(seen) == _norm(size) for size in sizes):
        return MATCH
    if answer.get("confidence", 0) < MIN_CONFIDENCE or answer.get("matches") is None:
        return UNCLEAR
    return MATCH if answer["matches"] else MISMATCH


# Each review gets a random angle, tone and length so they never read alike
# (the owner, 16.10.2026: «все отзывы однообразные»).
_ANGLES = (
    "착용감 (comfort when wearing)",
    "디자인과 색감 (design and colour)",
    "마감과 품질 (finish and quality)",
    "사이즈 (true to size)",
    "가격 대비 만족도 (value for money)",
    "배송과 포장 (delivery and packaging)",
    "사진과 실물 비교 (looks like the photos)",
    "선물용 (bought as a gift)",
    "코디 활용 (easy to match with outfits)",
    "재구매 의사 (would buy again)",
)
_TONES = (
    "calm and short, like a busy office worker",
    "cheerful, like a student",
    "detailed, like someone who compares a lot before buying",
    "simple and plain, no exclamation marks",
    "slightly enthusiastic, one exclamation mark at most",
    "practical, like a parent buying for the family",
)


def review_style(rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    angles = rng.sample(_ANGLES, 2)
    length = rng.randint(50, 70)
    tone = rng.choice(_TONES)
    return f"focus on {angles[0]} and {angles[1]}; tone: {tone}; about {length} characters"


def _item_line(order: Order) -> str:
    parts = [order.brand, order.model]
    line = " ".join(p for p in parts if p) or "товар"
    sizes = ordered_sizes(order)
    if sizes:
        line += f", размер {' / '.join(sizes)}"
    return line


@dataclass(frozen=True)
class ArrivalResult:
    order: Order
    status: str  # MATCH / MISMATCH / UNCLEAR / SKIPPED
    size_seen: str | None
    review_ko: str | None
    note: str | None
    moved_to_warehouse: bool
    error: str | None = None  # Gemini did not answer


class ArrivalService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        orders: OrderRepository,
        order_service: Any,
        auditor: Auditor,
        recognizer: Any = None,
    ):
        self._db = db
        self._clock = clock
        self._orders = orders
        self._order_service = order_service
        self._auditor = auditor
        self._recognizer = recognizer

    def _recent_reviews(self, limit: int = 8) -> list[str]:
        """The latest reviews: Gemini is told not to repeat their wording."""
        orders = [o for o in self._orders.list_all(self._db) if o.review_ko]
        orders.sort(key=lambda o: str(o.timestamp("updated_at") or ""), reverse=True)
        return [o.review_ko for o in orders[:limit] if o.review_ko]

    def waiting(self, actor: Actor, limit: int = 40) -> list[Order]:
        """Bought orders not at the warehouse yet, oldest buy-out first."""
        require_admin(actor)
        found = [o for o in self._orders.list_all(self._db) if o.status is OrderStatus.BOUGHT]
        oldest = datetime.min
        found.sort(key=lambda o: (o.timestamp("bought_at") or oldest).replace(tzinfo=None))
        return found[:limit]

    def record(
        self,
        actor: Actor,
        order_id: str,
        image: bytes,
        photo_url: str | None,
        thumbnail_url: str | None,
    ) -> ArrivalResult:
        """`image` is the standardised photo (process_image) for Gemini."""
        require_admin(actor)
        order_id = normalize_order_id(order_id)
        order = self._orders.get(self._db, order_id)
        if order is None:
            raise NotFoundError(f"Заказ {order_id} не найден.")
        if order.status not in (OrderStatus.BOUGHT, OrderStatus.WAREHOUSE):
            raise ConflictError(
                f"Заказ {order_id} сейчас «{order.status_raw}»: фото со склада — "
                "только для выкупленного заказа или заказа на складе."
            )

        answer: dict[str, Any] | None = None
        error = None
        if order.category == "watch":
            pass  # watches: the photo is only saved — no check, no review (owner, 16.10)
        elif self._recognizer is not None and hasattr(self._recognizer, "check_arrival"):
            try:
                answer = self._recognizer.check_arrival(
                    image,
                    item=_item_line(order),
                    sizes=ordered_sizes(order),
                    review_style=review_style(),
                    avoid=self._recent_reviews(),
                )
            except RecognitionError as exc:
                error = str(exc)
                logger.warning("Arrival check of %s failed: %s", order_id, exc)
        else:
            error = "Gemini не подключён"
        status = judge(order, answer)
        answer = answer or {}

        def fn(tx: Transaction) -> bool:
            current = self._orders.get(tx, order_id)
            if current is None:
                raise NotFoundError(f"Заказ {order_id} не найден.")
            moved = False
            if current.status is OrderStatus.BOUGHT:
                # Reads first (transaction rule), then its writes and ours.
                result = self._order_service._set_status(
                    tx, actor, [order_id], OrderStatus.WAREHOUSE
                )
                moved = order_id in result.updated
            now = self._clock.now()
            check = {
                "status": status,
                "size_seen": answer.get("size_seen"),
                "ordered_size": current.size,
                "note": answer.get("note"),
                "confidence": answer.get("confidence"),
                "error": error,
                "at": now,
            }
            fields: dict[str, Any] = {
                "arrival_photo_url": photo_url,
                "arrival_thumbnail_url": thumbnail_url,
                "arrival_check": check,
                "updated_at": now,
                "updated_by": actor.id,
            }
            if answer.get("review_ko"):
                fields["review_ko"] = answer["review_ko"]
            self._orders.update(tx, order_id, fields)
            self._auditor.record(
                tx,
                actor,
                now,
                action="order.arrival",
                entity_type="order",
                entity_id=order_id,
                before={"status": current.status_raw},
                after={"check": status, "size_seen": answer.get("size_seen")},
            )
            return moved

        moved = self._db.run_transaction(fn)
        return ArrivalResult(
            order=self._orders.get(self._db, order_id) or order,
            status=status,
            size_seen=answer.get("size_seen"),
            review_ko=answer.get("review_ko"),
            note=answer.get("note"),
            moved_to_warehouse=moved,
            error=error,
        )

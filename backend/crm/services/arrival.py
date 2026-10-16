"""«Пришло на склад» (the owner, 16.10.2026): the admin sends a photo of the item
that arrived (label, size tag, box). Gemini compares the size on the photo with
the ordered size (not for watches) and writes a short Korean review for the shop's
review points. The photo and the result are saved on the order (admin only) and a
«Выкуплен» order becomes «На складе». No money moves.
"""

import logging
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


def judge(order: Order, answer: dict[str, Any] | None) -> str:
    if order.category == "watch" or not order.size or answer is None:
        return SKIPPED
    seen = answer.get("size_seen")
    if not seen:
        return UNCLEAR
    if _norm(seen) == _norm(order.size):
        return MATCH
    if answer.get("confidence", 0) < MIN_CONFIDENCE or answer.get("matches") is None:
        return UNCLEAR
    return MATCH if answer["matches"] else MISMATCH


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
        if self._recognizer is not None and hasattr(self._recognizer, "check_arrival"):
            try:
                answer = self._recognizer.check_arrival(
                    image, order.title or "товар", order.size or "не указан"
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

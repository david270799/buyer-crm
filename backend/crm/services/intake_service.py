"""Orders from Telegram: one message with a photo becomes one new order.

The bot downloads and standardises the photo, asks Gemini what it is (see
services/recognition) and calls `accept`. Everything else happens here, in
one transaction:

* the same Telegram message never creates a second order (`intake` doc);
* the order is created with status `new` and no prices — no money moves;
* brand, model, size and link come from the validated recognition; what
  Gemini answered is kept for the admin (`recognition`, admin-only);
* the event feeds the history and the notifications as usual.

The client may create orders this way (it is how they order); everything
after that — buying, prices, statuses — stays admin-only.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from crm.domain.enums import OrderStatus, Role
from crm.domain.errors import PermissionDeniedError, ValidationError
from crm.domain.events import EventType
from crm.domain.ids import make_order_id, order_number
from crm.domain.models import Order
from crm.repositories import IntakeRepository, OrderRepository
from crm.services.common import Actor, Auditor, Clock
from crm.services.events import EventRecorder
from crm.services.image_service import StoredImage
from crm.services.order_service import (
    _MAX_LONG_TEXT,
    _MAX_SHORT_TEXT,
    ORDER_COUNTER,
    _clean_text,
    _clean_url,
    _describe,
)
from crm.services.recognition import Recognition, extract_urls
from crm.services.sequences import SequenceAllocator
from crm.storage import Database, DocumentExistsError, Transaction

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


@dataclass(frozen=True)
class IncomingOrder:
    chat_id: int
    message_id: int
    caption: str | None
    photo: StoredImage | None
    recognition: Recognition


@dataclass(frozen=True)
class IntakeResult:
    order: Order
    already_done: bool


def _safe(clean, value: str | None, *args) -> str | None:
    """Recognised values are best effort: an unusable one is dropped, not fatal."""
    try:
        return clean(value, *args)
    except ValidationError:
        return None


def _no_links(value: str | None) -> str | None:
    """Client-visible text never carries a link (links are the admin's)."""
    if value is None:
        return None
    return " ".join(_URL_RE.sub(" ", value).split()) or None


def client_note(caption: str | None, recognition: Recognition) -> str | None:
    """What the client wrote besides the size and the link (links are admin-only)."""
    if recognition.engine is not None:
        return recognition.note
    text = " ".join(_URL_RE.sub(" ", caption or "").split())
    if not text:
        return None
    compact = text.casefold().replace(" ", "")
    if recognition.size and compact == recognition.size.casefold().replace(" ", ""):
        return None
    return text[:500]


def recognition_doc(recognition: Recognition, now: datetime) -> dict[str, Any]:
    return {
        "engine": recognition.engine,
        "recognized": recognition.recognized,
        "brand": recognition.brand,
        "model": recognition.model,
        "category": recognition.category,
        "size": recognition.size,
        "confidence": recognition.confidence if recognition.engine else None,
        "error": recognition.error,
        "at": now,
    }


class IntakeService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        orders: OrderRepository,
        intake: IntakeRepository,
        sequences: SequenceAllocator,
        auditor: Auditor,
        events: EventRecorder,
    ):
        self._db = db
        self._clock = clock
        self._orders = orders
        self._intake = intake
        self._sequences = sequences
        self._auditor = auditor
        self._events = events

    def existing(self, chat_id: int, message_id: int) -> str | None:
        """Order already created from this message, if any (cheap pre-check)."""
        return self._intake.order_id(self._db, IntakeRepository.key(chat_id, message_id))

    def accept(self, actor: Actor, incoming: IncomingOrder) -> IntakeResult:
        if actor.role not in (Role.ADMIN, Role.CLIENT):
            raise PermissionDeniedError("Заказы принимаются только от клиента и администратора.")
        recognition = incoming.recognition
        link = recognition.link if recognition.link in extract_urls(incoming.caption) else None
        fields = {
            "brand": _safe(_clean_text, _no_links(recognition.brand), "Бренд", _MAX_SHORT_TEXT),
            "model": _safe(_clean_text, _no_links(recognition.model), "Модель", _MAX_SHORT_TEXT),
            "size": _safe(_clean_text, _no_links(recognition.size), "Размер", _MAX_SHORT_TEXT),
            "source_url": _safe(_clean_url, link, "Ссылка"),
            "photo_url": incoming.photo.photo_url if incoming.photo else None,
            "thumbnail_url": incoming.photo.thumbnail_url if incoming.photo else None,
            "client_comment": _safe(
                _clean_text,
                _no_links(client_note(incoming.caption, recognition)),
                "Комментарий",
                _MAX_LONG_TEXT,
            ),
        }
        key = IntakeRepository.key(incoming.chat_id, incoming.message_id)

        def fn(tx: Transaction) -> IntakeResult:
            existing_id = self._intake.order_id(tx, key)
            if existing_id is not None:
                existing = self._orders.get(tx, existing_id)
                if existing is not None:
                    return IntakeResult(order=existing, already_done=True)
            number = self._sequences.reserve(
                tx, ORDER_COUNTER, lambda n: self._orders.exists(tx, make_order_id(n))
            )
            order_id = make_order_id(number)
            now = self._clock.now()
            data = {
                "order_id": order_id,
                "status": OrderStatus.NEW.value,
                **fields,
                "purchase_price": None,
                "client_price": None,
                "profit": None,
                "charged_amount_krw": 0,  # only /buy charges
                "cargo_code": None,
                "shipment_id": None,
                "internal_comment": None,
                "source_chat_id": incoming.chat_id,
                "source_message_id": incoming.message_id,
                "attention_required": False,
                "recognition": recognition_doc(recognition, now),
                "created_at": now,
                "updated_at": now,
                "created_by": actor.id,
                "updated_by": actor.id,
            }
            self._orders.create(tx, order_id, data)
            self._intake.create(
                tx,
                key,
                order_id=order_id,
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                now=now,
            )
            self._sequences.commit(tx, ORDER_COUNTER, number, now)
            self._auditor.record(
                tx,
                actor,
                now,
                action="order.intake",
                entity_type="order",
                entity_id=order_id,
                before=None,
                after={
                    "status": OrderStatus.NEW.value,
                    "chat_id": incoming.chat_id,
                    "message_id": incoming.message_id,
                    "recognized_by": recognition.engine,
                },
            )
            created = Order.from_doc(order_id, data)
            self._events.record(
                tx,
                actor,
                now,
                EventType.ORDER_CREATED,
                f"Новый заказ {order_id}",
                body=_describe(created),
                order_ids=[order_id],
            )
            return IntakeResult(order=created, already_done=False)

        try:
            return self._sequences.run(ORDER_COUNTER, self._max_order_number, self._clock.now, fn)
        except DocumentExistsError:
            # The same message raced with itself (a Telegram redelivery).
            order_id = self.existing(incoming.chat_id, incoming.message_id)
            order = self._orders.get(self._db, order_id) if order_id else None
            if order is None:
                raise
            return IntakeResult(order=order, already_done=True)

    def _max_order_number(self) -> int:
        numbers = (order_number(doc_id) for doc_id in self._db.list_ids(self._orders.collection))
        return max((n for n in numbers if n is not None), default=0)

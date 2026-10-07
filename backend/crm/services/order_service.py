"""Order lifecycle.

Money rules (see docs/architecture.md, "Финансовые инварианты"):

* `/buy` charges `client_price` exactly once per order. The order's
  `charged_amount_krw` records what is currently charged; a repeated `/buy`
  with the same prices is a no-op, with different prices it is refused.
* `/cancel` refunds exactly `charged_amount_krw` and sets it to 0, so a
  repeated `/cancel` refunds nothing.
* Both run in one Firestore transaction together with the balance update,
  the ledger entry (deterministic ID, written with `create`) and the audit
  entry, so a crash or a retry can never leave money half-moved.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from crm.domain.enums import (
    CHARGED_STATUSES,
    STATUS_FLOW,
    STATUS_LABELS_RU,
    LedgerType,
    OrderStatus,
    Role,
)
from crm.domain.errors import ConflictError, NotFoundError, ValidationError
from crm.domain.events import Event, EventType
from crm.domain.ids import make_order_id, normalize_order_id, order_number
from crm.domain.models import Order, status_timestamp_field
from crm.domain.money import MAX_AMOUNT_KRW, format_krw
from crm.domain.timeutil import to_local
from crm.repositories import (
    EventRepository,
    IntakeRepository,
    OrderRepository,
    ProfitRepository,
    ShipmentRepository,
)
from crm.services.common import (
    UNSET,
    Actor,
    Auditor,
    Clock,
    provided_fields,
    require_admin,
    require_bulk_size,
)
from crm.services.events import EventRecorder
from crm.services.ledger import (
    BalanceChange,
    BalanceLedger,
    order_charge_entry_id,
    order_refund_entry_id,
)
from crm.services.sequences import SequenceAllocator
from crm.storage import Database, DocumentExistsError, Transaction
from crm.storage.blobs import BlobStorage

logger = logging.getLogger(__name__)

ORDER_COUNTER = "orders"
_SENT = (OrderStatus.CARGO, OrderStatus.DELIVERED)

_MAX_SHORT_TEXT = 200
_MAX_LONG_TEXT = 2000

# Statuses that have their own command because they move money.
_STATUS_HAS_OWN_COMMAND = {
    OrderStatus.BOUGHT: "Статус «Выкуплен» ставится только через /buy <номер> <закупка> "
    "<цена клиенту> — эта команда списывает деньги с баланса.",
    OrderStatus.CANCELLED: "Отмена выполняется только через /cancel <номер> — эта команда "
    "возвращает деньги на баланс.",
    OrderStatus.NEW: "Вернуть заказ в статус «Новый» нельзя: по выкупленному заказу "
    "уже списаны деньги. Для отмены используйте /cancel.",
}


def label(status: OrderStatus | None) -> str:
    return STATUS_LABELS_RU[status] if status else "неизвестный статус"


@dataclass
class NewOrder:
    brand: str | None = None
    model: str | None = None
    size: str | None = None
    source_url: str | None = None
    purchase_price: int | None = None
    client_price: int | None = None
    client_comment: str | None = None
    internal_comment: str | None = None
    photo_url: str | None = None
    thumbnail_url: str | None = None
    source_chat_id: int | None = None
    source_message_id: int | None = None
    attention_required: bool = False


@dataclass(frozen=True)
class ProfitLine:
    """One line of the profit page: an order's profit or an extra profit entry."""

    amount_krw: int
    at: datetime | None
    order: Order | None = None
    comment: str | None = None


@dataclass
class BuyResult:
    order: Order
    already_done: bool
    change: BalanceChange | None = None


@dataclass
class CancelResult:
    order: Order
    already_done: bool
    refunded_krw: int = 0
    change: BalanceChange | None = None


@dataclass
class RebuyResult:
    order: Order
    already_done: bool
    change: BalanceChange | None = None


@dataclass
class DeleteResult:
    deleted: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    # Refunds of what was still charged for the deleted orders.
    refunds: list[tuple[str, int]] = field(default_factory=list)
    change: BalanceChange | None = None
    # Number the next new order gets (None if no order was ever numbered).
    next_order_id: str | None = None

    @property
    def refunded_krw(self) -> int:
        return sum(amount for _, amount in self.refunds)


@dataclass
class DiscountResult:
    # (order_id, old client price, new client price)
    updated: list[tuple[str, int, int]] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    # Refunded to the balance for orders already paid.
    refunded_krw: int = 0
    change: BalanceChange | None = None


@dataclass
class DeletePreview:
    """What `delete_orders` would do, for the confirmation question."""

    orders: list[Order] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def refund_krw(self) -> int:
        return sum(o.charged_amount_krw for o in self.orders)


@dataclass
class BulkResult:
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def _clean_text(value: str | None, name: str, max_len: int) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if len(text) > max_len:
        raise ValidationError(f"Поле «{name}» слишком длинное (максимум {max_len} символов).")
    return text or None


def _check_price(value: int | None, name: str, *, allow_zero: bool) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{name}: нужна целая сумма в вонах.")
    if value < 0 or (value == 0 and not allow_zero):
        raise ValidationError(f"{name} должна быть больше нуля.")
    if value > MAX_AMOUNT_KRW:
        raise ValidationError(f"{name} больше допустимого лимита {format_krw(MAX_AMOUNT_KRW)}.")


def _clean_url(value: str | None, name: str) -> str | None:
    """Only http(s) links: they are rendered as <a href> in the Mini App."""
    text = _clean_text(value, name, _MAX_LONG_TEXT)
    if text is None:
        return None
    if not text.lower().startswith(("https://", "http://")):
        raise ValidationError(f"«{name}»: ссылка должна начинаться с https://")
    return text


# Photos on the server's own disk are served from here (LocalBlobStorage).
_MEDIA_PREFIX = "/media/"


def _clean_photo_url(value: str | None, name: str) -> str | None:
    """A photo is an http(s) URL or a file of our own media storage (`/media/...`)."""
    text = _clean_text(value, name, _MAX_LONG_TEXT)
    if text is None:
        return None
    if text.startswith(_MEDIA_PREFIX) and ".." not in text and "//" not in text:
        return text
    return _clean_url(text, name)


@dataclass
class OrderUpdate:
    """Partial update of non-financial order fields (UNSET = keep, None = clear).

    Prices can be edited only while the order is `new` and nothing is charged;
    after /buy a price change moves money and is a separate operation.
    """

    brand: str | None = UNSET
    model: str | None = UNSET
    size: str | None = UNSET
    source_url: str | None = UNSET
    photo_url: str | None = UNSET
    thumbnail_url: str | None = UNSET
    client_comment: str | None = UNSET
    internal_comment: str | None = UNSET
    attention_required: bool = UNSET
    purchase_price: int | None = UNSET
    client_price: int | None = UNSET


@dataclass
class BulkUpdate:
    client_comment: str | None = UNSET
    internal_comment: str | None = UNSET
    attention_required: bool = UNSET


SORTS = ("newest", "oldest", "price_desc", "price_asc")


@dataclass
class OrderQuery:
    status: OrderStatus | None = None
    search: str | None = None
    attention: bool | None = None
    sort: str = "newest"
    offset: int = 0
    limit: int = 50


@dataclass
class OrderPage:
    items: list[Order]
    total: int


@dataclass
class OrdersOverview:
    status_counts: dict[str, int]
    attention_count: int
    total: int
    active: int
    # Admin only (None for the client):
    profit_total_krw: int | None = None
    profit_month_krw: int | None = None
    recent: list[Order] = field(default_factory=list)


def _clean_update_fields(values: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for name, value in values.items():
        if name in ("brand", "model", "size"):
            cleaned[name] = _clean_text(value, name, _MAX_SHORT_TEXT)
        elif name in ("client_comment", "internal_comment"):
            cleaned[name] = _clean_text(value, "Комментарий", _MAX_LONG_TEXT)
        elif name == "source_url":
            cleaned[name] = _clean_url(value, "Ссылка")
        elif name in ("photo_url", "thumbnail_url"):
            cleaned[name] = _clean_photo_url(value, "Фото")
        elif name == "attention_required":
            if not isinstance(value, bool):
                raise ValidationError("attention_required должен быть true или false.")
            cleaned[name] = value
        elif name in ("purchase_price", "client_price"):
            _check_price(value, "Цена", allow_zero=True)
            cleaned[name] = value
        else:  # pragma: no cover - programming error
            raise ValueError(f"Unknown order field {name}")
    return cleaned


def _matches(order: Order, needle: str, admin: bool) -> bool:
    haystack = [
        order.id,
        order.brand,
        order.model,
        order.size,
        order.cargo_code,
        order.shipment_id,
        order.client_comment,
    ]
    if admin:
        haystack.append(order.internal_comment)
    return any(needle in value.lower() for value in haystack if value)


def _sort_key(sort: str):
    if sort in ("price_desc", "price_asc"):
        return lambda o: (o.client_price or 0, order_number(o.id) or 0)
    return lambda o: order_number(o.id) or 0


class OrderService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        orders: OrderRepository,
        ledger: BalanceLedger,
        sequences: SequenceAllocator,
        auditor: Auditor,
        events: EventRecorder,
        *,
        event_repo: EventRepository | None = None,
        intake: IntakeRepository | None = None,
        blobs: BlobStorage | None = None,
        profit: ProfitRepository | None = None,
    ):
        self._db = db
        self._clock = clock
        self._orders = orders
        self._ledger = ledger
        self._sequences = sequences
        self._auditor = auditor
        self._events = events
        self._event_repo = event_repo or EventRepository()
        self._intake = intake or IntakeRepository()
        self._blobs = blobs
        self._profit = profit
        self._shipments = ShipmentRepository()

    # --- reads -------------------------------------------------------------

    def get_order(self, actor: Actor, order_id: str) -> Order:
        """Any role may read; callers must render through crm.domain.views."""
        order_id = normalize_order_id(order_id)
        order = self._orders.get(self._db, order_id)
        if order is None:
            raise NotFoundError(f"Заказ {order_id} не найден.")
        return order

    def get_orders(self, actor: Actor, order_ids: Sequence[str]) -> dict[str, Order]:
        """Existing orders among `order_ids` (missing ones are left out)."""
        ids = list(dict.fromkeys(normalize_order_id(i) for i in order_ids))
        if not ids:
            return {}
        found = self._orders.get_many(self._db, ids)
        return {order_id: order for order_id, order in found.items() if order is not None}

    def list_orders(self, actor: Actor, query: OrderQuery) -> OrderPage:
        """Filter, search and sort in memory.

        One CRM with one client has hundreds to a few thousand orders, so
        reading the collection is cheap and keeps legacy documents (odd
        status spellings, missing fields) searchable. Revisit with indexed
        queries if the collection grows past ~10k documents.
        """
        if query.sort not in SORTS:
            raise ValidationError(f"Неизвестная сортировка: {query.sort}")
        orders = self._orders.list_all(self._db)
        if query.status is not None:
            orders = [o for o in orders if o.status is query.status]
        if query.attention is not None:
            orders = [o for o in orders if o.attention_required is query.attention]
        needle = (query.search or "").strip().lower()
        if needle:
            admin = actor.role is Role.ADMIN
            orders = [o for o in orders if _matches(o, needle, admin)]
        orders.sort(key=_sort_key(query.sort), reverse=query.sort in ("newest", "price_desc"))
        limit = max(1, min(query.limit, 200))
        offset = max(0, query.offset)
        return OrderPage(items=orders[offset : offset + limit], total=len(orders))

    def overview(self, actor: Actor, recent: int = 6) -> OrdersOverview:
        orders = self._orders.list_all(self._db)
        counts = {status.value: 0 for status in (*STATUS_FLOW, OrderStatus.CANCELLED)}
        for order in orders:
            if order.status is not None:
                counts[order.status.value] += 1
        active = sum(1 for o in orders if o.status in STATUS_FLOW[:-1])
        result = OrdersOverview(
            status_counts=counts,
            attention_count=sum(1 for o in orders if o.attention_required),
            total=len(orders),
            active=active,
            recent=sorted(orders, key=_sort_key("newest"), reverse=True)[:recent],
        )
        if actor.role is Role.ADMIN:
            month = to_local(self._clock.now()).strftime("%Y-%m")
            charged = [o for o in orders if o.status in CHARGED_STATUSES and o.profit is not None]
            result.profit_total_krw = sum(o.profit for o in charged)
            result.profit_month_krw = sum(
                o.profit
                for o in charged
                if isinstance(o.timestamp("bought_at"), datetime)
                and to_local(o.timestamp("bought_at")).strftime("%Y-%m") == month
            )
            # The admin's extra profit entries (never shown to the client).
            for entry in self._profit.list_all(self._db) if self._profit else []:
                result.profit_total_krw += entry.amount_krw
                if entry.created_at and to_local(entry.created_at).strftime("%Y-%m") == month:
                    result.profit_month_krw += entry.amount_krw
        return result

    def profit_lines(self, actor: Actor, period: str = "all") -> list[ProfitLine]:
        """What the profit on the dashboard is made of (same rules as `overview`):
        each bought order's profit by its purchase date, plus the admin's extra
        profit entries. `period`: "month" (this month in Seoul) or "all". Newest first."""
        require_admin(actor)
        month = to_local(self._clock.now()).strftime("%Y-%m")

        def in_period(when: datetime | None) -> bool:
            if period != "month":
                return True
            return isinstance(when, datetime) and to_local(when).strftime("%Y-%m") == month

        lines: list[ProfitLine] = []
        for order in self._orders.list_all(self._db):
            if order.status not in CHARGED_STATUSES or order.profit is None:
                continue
            when = order.timestamp("bought_at")
            when = when if isinstance(when, datetime) else None
            if in_period(when):
                lines.append(ProfitLine(order.profit, when, order=order))
        for entry in self._profit.list_all(self._db) if self._profit else []:
            if in_period(entry.created_at):
                lines.append(ProfitLine(entry.amount_krw, entry.created_at, comment=entry.comment))
        oldest = datetime.min.replace(tzinfo=UTC)
        lines.sort(key=lambda line: line.at or oldest, reverse=True)
        return lines

    # --- edit (no money) ---------------------------------------------------

    def update_details(self, actor: Actor, order_id: str, update: OrderUpdate) -> Order:
        require_admin(actor)
        order_id = normalize_order_id(order_id)
        changes = _clean_update_fields(provided_fields(update))
        if not changes:
            raise ValidationError("Нет изменений.")

        def fn(tx: Transaction) -> Order:
            order = self._require_order(tx, order_id)
            price_change = {"purchase_price", "client_price"} & changes.keys()
            if price_change and (order.status is not OrderStatus.NEW or order.is_charged):
                raise ConflictError(
                    f"Заказ {order_id} уже выкуплен: цену нельзя изменить простым "
                    "редактированием, это отдельная финансовая операция."
                )
            fields: dict[str, Any] = dict(changes)
            if price_change:
                purchase = changes.get("purchase_price", order.purchase_price)
                client = changes.get("client_price", order.client_price)
                fields["profit"] = (
                    client - purchase if client is not None and purchase is not None else None
                )
            now = self._clock.now()
            fields.update({"updated_at": now, "updated_by": actor.id})
            self._orders.update(tx, order_id, fields)
            self._auditor.record(
                tx,
                actor,
                now,
                action="order.update",
                entity_type="order",
                entity_id=order_id,
                before={name: getattr(order, name) for name in changes},
                after=changes,
            )
            self._record_comment_events(tx, actor, now, [order], changes)
            return replace(
                order,
                **{k: v for k, v in fields.items() if k not in ("updated_at", "updated_by")},
                timestamps={**order.timestamps, "updated_at": now},
            )

        return self._db.run_transaction(fn)

    def bulk_update(self, actor: Actor, order_ids: Sequence[str], update: BulkUpdate) -> BulkResult:
        require_admin(actor)
        ids = list(dict.fromkeys(normalize_order_id(i) for i in order_ids))
        require_bulk_size(ids)
        changes = _clean_update_fields(provided_fields(update))
        if not changes:
            raise ValidationError("Нет изменений.")

        def fn(tx: Transaction) -> BulkResult:
            orders = self._orders.get_many(tx, ids)
            result = BulkResult()
            now = self._clock.now()
            for order_id in ids:
                order = orders[order_id]
                if order is None:
                    result.not_found.append(order_id)
                    continue
                self._orders.update(
                    tx, order_id, {**changes, "updated_at": now, "updated_by": actor.id}
                )
                self._auditor.record(
                    tx,
                    actor,
                    now,
                    action="order.bulk_update",
                    entity_type="order",
                    entity_id=order_id,
                    before={name: getattr(order, name) for name in changes},
                    after=changes,
                )
                result.updated.append(order_id)
            updated = [orders[i] for i in result.updated if orders[i] is not None]
            self._record_comment_events(tx, actor, now, updated, changes)
            return result

        return self._db.run_transaction(fn)

    def _record_comment_events(
        self, tx: Transaction, actor: Actor, now: datetime, orders: list[Order], changes: dict
    ) -> None:
        """A client comment and a newly raised "attention" are news for the client."""
        if not orders:
            return
        comment = changes.get("client_comment")
        raised = changes.get("attention_required") is True and any(
            not o.attention_required for o in orders
        )
        comment_changed = comment is not None and any(o.client_comment != comment for o in orders)
        ids = [o.id for o in orders]
        if raised:
            reason = comment or next((o.client_comment for o in orders if o.client_comment), None)
            self._events.record(
                tx,
                actor,
                now,
                EventType.ATTENTION,
                f"Требуется внимание: {_ids(ids)}",
                body=reason,
                order_ids=ids,
            )
        elif comment_changed:
            self._events.record(
                tx,
                actor,
                now,
                EventType.COMMENT,
                f"Комментарий к {'заказу' if len(ids) == 1 else 'заказам'} {_ids(ids)}",
                body=comment,
                order_ids=ids,
            )

    # --- create ------------------------------------------------------------

    def create_order(self, actor: Actor, new: NewOrder) -> Order:
        require_admin(actor)
        _check_price(new.purchase_price, "Закупочная цена", allow_zero=True)
        _check_price(new.client_price, "Цена для клиента", allow_zero=True)
        fields = {
            "brand": _clean_text(new.brand, "Бренд", _MAX_SHORT_TEXT),
            "model": _clean_text(new.model, "Модель", _MAX_SHORT_TEXT),
            "size": _clean_text(new.size, "Размер", _MAX_SHORT_TEXT),
            "source_url": _clean_url(new.source_url, "Ссылка"),
            "photo_url": _clean_photo_url(new.photo_url, "Фото"),
            "thumbnail_url": _clean_photo_url(new.thumbnail_url, "Миниатюра"),
            "client_comment": _clean_text(new.client_comment, "Комментарий", _MAX_LONG_TEXT),
            "internal_comment": _clean_text(
                new.internal_comment, "Внутренний комментарий", _MAX_LONG_TEXT
            ),
        }
        profit = (
            new.client_price - new.purchase_price
            if new.client_price is not None and new.purchase_price is not None
            else None
        )

        def fn(tx: Transaction) -> Order:
            number = self._sequences.reserve(
                tx, ORDER_COUNTER, lambda n: self._orders.exists(tx, make_order_id(n))
            )
            order_id = make_order_id(number)
            now = self._clock.now()
            data = {
                "order_id": order_id,
                "status": OrderStatus.NEW.value,
                **fields,
                "purchase_price": new.purchase_price,
                "client_price": new.client_price,
                "profit": profit,
                # A new order is never charged; only /buy charges.
                "charged_amount_krw": 0,
                "cargo_code": None,
                "shipment_id": None,
                "source_chat_id": new.source_chat_id,
                "source_message_id": new.source_message_id,
                "attention_required": new.attention_required,
                "created_at": now,
                "updated_at": now,
                "created_by": actor.id,
                "updated_by": actor.id,
            }
            self._orders.create(tx, order_id, data)
            self._sequences.commit(tx, ORDER_COUNTER, number, now)
            self._auditor.record(
                tx,
                actor,
                now,
                action="order.create",
                entity_type="order",
                entity_id=order_id,
                before=None,
                after={"status": OrderStatus.NEW.value},
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
            return created

        return self._sequences.run(ORDER_COUNTER, self._max_order_number, self._clock.now, fn)

    def duplicate(self, actor: Actor, order_id: str, count: int = 1) -> list[Order]:
        """«Копия»: the client wants the same item several times. Each copy is a new
        order `new` with the same photo, brand, model, size and comments, but no
        prices and no link to the Telegram message (the photo's reaction follows
        the original). Prices are set on each copy separately."""
        require_admin(actor)
        if not 1 <= count <= 10:
            raise ValidationError("Количество копий — от 1 до 10.")
        source = self.get_order(actor, order_id)
        template = NewOrder(
            brand=source.brand,
            model=source.model,
            size=source.size,
            source_url=source.source_url,
            client_comment=source.client_comment,
            internal_comment=f"Копия {source.id}",
            photo_url=source.photo_url,
            thumbnail_url=source.thumbnail_url,
        )
        return [self.create_order(actor, template) for _ in range(count)]

    def _max_order_number(self) -> int:
        numbers = (order_number(doc_id) for doc_id in self._db.list_ids(self._orders.collection))
        return max((n for n in numbers if n is not None), default=0)

    # --- buy ---------------------------------------------------------------

    def buy(self, actor: Actor, order_id: str, purchase_price: int, client_price: int) -> BuyResult:
        require_admin(actor)
        order_id = normalize_order_id(order_id)
        _check_price(purchase_price, "Закупочная цена", allow_zero=True)
        _check_price(client_price, "Цена для клиента", allow_zero=False)

        def fn(tx: Transaction) -> BuyResult:
            order = self._require_order(tx, order_id)
            if order.status is OrderStatus.CANCELLED:
                raise ConflictError(f"Заказ {order_id} отменён — выкуп невозможен.")

            if order.status is not OrderStatus.NEW:
                if not order.is_charged:
                    raise ConflictError(
                        f"Заказ {order_id} в статусе «{label(order.status)}», но списание по "
                        "нему не зафиксировано. Повторное списание не выполняется — проверьте "
                        "заказ вручную."
                    )
                if order.purchase_price == purchase_price and order.client_price == client_price:
                    return BuyResult(order=order, already_done=True)
                raise ConflictError(
                    f"Заказ {order_id} уже выкуплен: закупка {_fmt(order.purchase_price)}, "
                    f"клиенту {_fmt(order.client_price)}, "
                    f"списано {format_krw(order.charged_amount_krw)}.\n"
                    "Повторное списание не выполняется. Если магазин отменил заказ и вы "
                    "выкупили в другом — используйте перезаказ: "
                    "/rebuy <номер> <закупка> <цена клиенту>."
                )
            if order.is_charged:
                raise ConflictError(
                    f"Заказ {order_id} в статусе «Новый», но по нему уже числится списание "
                    f"{format_krw(order.charged_amount_krw)}. Проверьте заказ вручную."
                )

            client = self._ledger.load_client(tx)
            now = self._clock.now()
            profit = client_price - purchase_price
            self._orders.update(
                tx,
                order_id,
                {
                    "status": OrderStatus.BOUGHT.value,
                    "purchase_price": purchase_price,
                    "client_price": client_price,
                    "profit": profit,
                    "charged_amount_krw": client_price,
                    "purchases": [_purchase(purchase_price, client_price, order.source_url, now)],
                    "bought_at": now,
                    "updated_at": now,
                    "updated_by": actor.id,
                },
            )
            change = self._ledger.apply(
                tx,
                client,
                entry_id=order_charge_entry_id(order_id),
                type=LedgerType.ORDER_CHARGE,
                amount_krw=-client_price,
                actor=actor,
                now=now,
                order_id=order_id,
                comment=order.title,
            )
            self._auditor.record(
                tx,
                actor,
                now,
                action="order.buy",
                entity_type="order",
                entity_id=order_id,
                before={
                    "status": order.status_raw,
                    "purchase_price": order.purchase_price,
                    "client_price": order.client_price,
                },
                after={
                    "status": OrderStatus.BOUGHT.value,
                    "purchase_price": purchase_price,
                    "client_price": client_price,
                    "charged_amount_krw": client_price,
                    "balance_after": change.balance_after,
                },
            )
            bought = replace(
                order,
                status=OrderStatus.BOUGHT,
                status_raw=OrderStatus.BOUGHT.value,
                purchase_price=purchase_price,
                client_price=client_price,
                profit=profit,
                charged_amount_krw=client_price,
                purchases=[_purchase(purchase_price, client_price, order.source_url, now)],
                timestamps={**order.timestamps, "bought_at": now, "updated_at": now},
            )
            self._events.record(
                tx,
                actor,
                now,
                EventType.ORDER_BOUGHT,
                f"Заказ {order_id} выкуплен",
                body=f"{_describe(bought)} · {format_krw(client_price)}",
                order_ids=[order_id],
                amount_krw=-client_price,
            )
            return BuyResult(order=bought, already_done=False, change=change)

        try:
            return self._db.run_transaction(fn)
        except DocumentExistsError:
            raise ConflictError(
                f"Списание по заказу {order_id} уже есть в истории транзакций. "
                "Повторное списание заблокировано — проверьте заказ вручную."
            ) from None

    # --- cancel ------------------------------------------------------------

    def cancel(self, actor: Actor, order_id: str) -> CancelResult:
        require_admin(actor)
        order_id = normalize_order_id(order_id)

        def fn(tx: Transaction) -> CancelResult:
            order = self._require_order(tx, order_id)
            if order.status is OrderStatus.CANCELLED:
                return CancelResult(order=order, already_done=True)
            if order.status in (OrderStatus.CARGO, OrderStatus.DELIVERED):
                raise ConflictError(
                    f"Заказ {order_id} уже в статусе «{label(order.status)}». После отправки "
                    "заказ не отменяется и деньги за него не возвращаются."
                )
            if order.shipment_id:
                raise ConflictError(
                    f"Заказ {order_id} входит в отправку {order.shipment_id} — отмена невозможна."
                )

            refund = order.charged_amount_krw
            client = self._ledger.load_client(tx) if refund > 0 else None
            now = self._clock.now()
            fields = {
                "status": OrderStatus.CANCELLED.value,
                "charged_amount_krw": 0,
                "cancelled_at": now,
                "updated_at": now,
                "updated_by": actor.id,
            }
            if refund > 0:
                fields["refunded_amount_krw"] = refund
            self._orders.update(tx, order_id, fields)

            change = None
            if client is not None:
                change = self._ledger.apply(
                    tx,
                    client,
                    entry_id=order_refund_entry_id(order_id),
                    type=LedgerType.ORDER_REFUND,
                    amount_krw=refund,
                    actor=actor,
                    now=now,
                    order_id=order_id,
                    comment=order.title,
                )
            self._auditor.record(
                tx,
                actor,
                now,
                action="order.cancel",
                entity_type="order",
                entity_id=order_id,
                before={"status": order.status_raw, "charged_amount_krw": order.charged_amount_krw},
                after={
                    "status": OrderStatus.CANCELLED.value,
                    "charged_amount_krw": 0,
                    "refunded_krw": refund,
                    "balance_after": change.balance_after if change else None,
                },
            )
            cancelled = replace(
                order,
                status=OrderStatus.CANCELLED,
                status_raw=OrderStatus.CANCELLED.value,
                charged_amount_krw=0,
                timestamps={**order.timestamps, "cancelled_at": now, "updated_at": now},
            )
            self._events.record(
                tx,
                actor,
                now,
                EventType.ORDER_CANCELLED,
                f"Заказ {order_id} отменён",
                body=(
                    f"{_describe(order)}\nВозврат на баланс: {format_krw(refund, signed=True)}"
                    if refund
                    else _describe(order)
                ),
                order_ids=[order_id],
                amount_krw=refund or None,
            )
            return CancelResult(
                order=cancelled, already_done=False, refunded_krw=refund, change=change
            )

        try:
            return self._db.run_transaction(fn)
        except DocumentExistsError:
            raise ConflictError(
                f"Возврат по заказу {order_id} уже есть в истории транзакций. "
                "Повторный возврат заблокирован — проверьте заказ вручную."
            ) from None

    # --- status ------------------------------------------------------------

    def set_status(
        self, actor: Actor, order_ids: Sequence[str], new_status: OrderStatus
    ) -> BulkResult:
        require_admin(actor)
        # "Выкуплен" is set by /buy (it charges); the one exception is taking a
        # mistaken "На складе" back — the order is already paid, no money moves.
        rollback = new_status is OrderStatus.BOUGHT
        if new_status in _STATUS_HAS_OWN_COMMAND and not rollback:
            raise ValidationError(_STATUS_HAS_OWN_COMMAND[new_status])
        ids = list(dict.fromkeys(normalize_order_id(i) for i in order_ids))
        require_bulk_size(ids)
        ts_field = status_timestamp_field(new_status)

        def fn(tx: Transaction) -> BulkResult:
            orders = self._orders.get_many(tx, ids)
            result = BulkResult()
            to_update: list[Order] = []
            for order_id in ids:
                order = orders[order_id]
                if order is None:
                    result.not_found.append(order_id)
                elif order.status is None:
                    result.skipped.append((order_id, f"неизвестный статус «{order.status_raw}»"))
                elif order.status is OrderStatus.NEW:
                    result.skipped.append((order_id, "не выкуплен — сначала /buy"))
                elif order.status is OrderStatus.CANCELLED:
                    result.skipped.append((order_id, "отменён"))
                elif order.status is new_status:
                    result.unchanged.append(order_id)
                elif rollback and not (order.status is OrderStatus.WAREHOUSE and order.is_charged):
                    result.skipped.append(
                        (order_id, "«Выкуплен» можно вернуть только из «На складе»")
                    )
                elif new_status is OrderStatus.CARGO and not order.shipment_id:
                    result.skipped.append((order_id, "нет отправки — используйте /cargo"))
                elif new_status is OrderStatus.WAREHOUSE and order.shipment_id:
                    result.skipped.append((order_id, f"входит в отправку {order.shipment_id}"))
                else:
                    to_update.append(order)

            now = self._clock.now()
            for order in to_update:
                fields = {"status": new_status.value, "updated_at": now, "updated_by": actor.id}
                if not rollback:  # keep the real purchase date (profit by month)
                    fields[ts_field] = now
                self._orders.update(tx, order.id, fields)
                self._auditor.record(
                    tx,
                    actor,
                    now,
                    action="order.status",
                    entity_type="order",
                    entity_id=order.id,
                    before={"status": order.status_raw},
                    after={"status": new_status.value},
                )
                result.updated.append(order.id)
            if result.updated:
                event_type, title = (
                    (EventType.ORDER_STATUS, "Статус возвращён: «Выкуплен»")
                    if rollback
                    else _STATUS_EVENTS.get(new_status, (EventType.ORDER_STATUS, "Статус обновлён"))
                )
                self._events.record(
                    tx,
                    actor,
                    now,
                    event_type,
                    f"{title}: {_ids(result.updated)}",
                    order_ids=result.updated,
                )
            return result

        return self._db.run_transaction(fn)

    # --- re-purchase ---------------------------------------------------------

    def rebuy(
        self,
        actor: Actor,
        order_id: str,
        purchase_price: int,
        client_price: int,
        *,
        source_url: str | None = UNSET,
        reason: str | None = None,
    ) -> RebuyResult:
        """The shop cancelled a bought order and it was bought elsewhere.

        Only the difference between the new client price and what is already
        charged moves (charged or refunded) — one `order_rebuy` ledger entry.
        Submitting the same purchase again changes nothing.
        """
        require_admin(actor)
        order_id = normalize_order_id(order_id)
        _check_price(purchase_price, "Закупочная цена", allow_zero=True)
        _check_price(client_price, "Цена для клиента", allow_zero=False)
        link = _clean_url(source_url, "Ссылка") if source_url is not UNSET else UNSET
        reason = _clean_text(reason, "Причина", _MAX_LONG_TEXT)

        def fn(tx: Transaction) -> RebuyResult:
            order = self._require_order(tx, order_id)
            if order.status not in (OrderStatus.BOUGHT, OrderStatus.WAREHOUSE):
                raise ConflictError(
                    f"Перезаказ возможен только для выкупленного заказа до отправки; "
                    f"{order_id} сейчас «{label(order.status)}»."
                )
            if order.shipment_id:
                raise ConflictError(f"Заказ {order_id} уже в отправке {order.shipment_id}.")
            if not order.is_charged:
                raise ConflictError(
                    f"По заказу {order_id} не записано списание — перезаказ невозможен."
                )
            new_link = order.source_url if link is UNSET else link
            if (
                purchase_price == order.purchase_price
                and client_price == order.client_price
                and new_link == order.source_url
            ):
                return RebuyResult(order=order, already_done=True)

            delta = client_price - order.charged_amount_krw
            client = self._ledger.load_client(tx) if delta else None
            now = self._clock.now()
            seq = order.rebuy_count + 1
            history = order.purchases or [
                _purchase(
                    order.purchase_price,
                    order.client_price,
                    order.source_url,
                    order.timestamp("bought_at"),
                )
            ]
            history = [*history[:-1], {**history[-1], "replaced_at": now}]
            history.append(_purchase(purchase_price, client_price, new_link, now, reason))
            profit = client_price - purchase_price
            fields: dict[str, Any] = {
                "status": OrderStatus.BOUGHT.value,
                "purchase_price": purchase_price,
                "client_price": client_price,
                "profit": profit,
                "charged_amount_krw": client_price,
                "purchases": history,
                "rebuy_count": seq,
                "bought_at": now,
                "updated_at": now,
                "updated_by": actor.id,
            }
            if link is not UNSET:
                fields["source_url"] = link
            self._orders.update(tx, order_id, fields)

            change = None
            if client is not None:
                change = self._ledger.apply(
                    tx,
                    client,
                    entry_id=f"order_rebuy_{order_id}_{seq}",
                    type=LedgerType.ORDER_REBUY,
                    amount_krw=-delta,
                    actor=actor,
                    now=now,
                    order_id=order_id,
                    comment=f"Перезаказ: {format_krw(order.client_price or 0)} → "
                    f"{format_krw(client_price)}",
                )
            self._auditor.record(
                tx,
                actor,
                now,
                action="order.rebuy",
                entity_type="order",
                entity_id=order_id,
                before={
                    "status": order.status_raw,
                    "purchase_price": order.purchase_price,
                    "client_price": order.client_price,
                    "source_url": order.source_url,
                },
                after={
                    "purchase_price": purchase_price,
                    "client_price": client_price,
                    "source_url": new_link,
                    "delta_krw": -delta,
                },
            )
            lines = [reason] if reason else []
            if client_price != order.client_price:
                lines.append(
                    f"Цена: {format_krw(order.client_price or 0)} → {format_krw(client_price)}"
                )
            self._events.record(
                tx,
                actor,
                now,
                EventType.ORDER_REBOUGHT,
                f"Заказ {order_id} перезаказан",
                body="\n".join(lines) or "Товар выкуплен заново в другом магазине.",
                order_ids=[order_id],
                amount_krw=-delta if delta else None,
            )
            rebought = replace(
                order,
                status=OrderStatus.BOUGHT,
                status_raw=OrderStatus.BOUGHT.value,
                purchase_price=purchase_price,
                client_price=client_price,
                profit=profit,
                charged_amount_krw=client_price,
                source_url=new_link,
                purchases=history,
                rebuy_count=seq,
                timestamps={**order.timestamps, "bought_at": now, "updated_at": now},
            )
            return RebuyResult(order=rebought, already_done=False, change=change)

        try:
            return self._db.run_transaction(fn)
        except DocumentExistsError:
            raise ConflictError(
                f"Перезаказ по заказу {order_id} уже проведён. Обновите данные и повторите."
            ) from None

    # --- discount ----------------------------------------------------------

    def discount(
        self,
        actor: Actor,
        order_ids: Sequence[str],
        percent: Decimal,
        idempotency_key: str | None = None,
    ) -> DiscountResult:
        """Lower the client price of each order by `percent` (to the won, no rounding
        to hundreds). For an order already paid the discount comes back to the
        balance — one ledger entry per order, so a later cancel or delete still
        nets to zero. Only before shipping (the owner's decision); cancelled
        orders and orders without a price are skipped. A repeated request with
        the same key changes nothing."""
        require_admin(actor)
        percent = Decimal(str(percent))
        if not (Decimal(0) < percent < Decimal(100)):
            raise ValidationError("Скидка должна быть больше 0% и меньше 100%.")
        if percent != percent.quantize(Decimal("0.01")):
            raise ValidationError("Скидка — не больше двух знаков после запятой.")
        ids = list(dict.fromkeys(normalize_order_id(i) for i in order_ids))
        require_bulk_size(ids)
        key = idempotency_key or self._db.new_id()
        label = f"{percent.normalize():f}%"

        def fn(tx: Transaction) -> DiscountResult:
            result = DiscountResult()
            raw = tx.get_many(self._orders.collection, ids)
            targets: list[tuple[Order, dict[str, Any], int]] = []
            for order_id in ids:
                data = raw.get(order_id)
                if data is None:
                    result.not_found.append(order_id)
                    continue
                order = Order.from_doc(order_id, data)
                if any(d.get("key") == key for d in data.get("discounts") or []):
                    result.unchanged.append(order_id)
                elif order.status in (OrderStatus.CANCELLED, None):
                    result.skipped.append((order_id, "отменён"))
                elif (
                    order.status in (OrderStatus.CARGO, OrderStatus.DELIVERED) or order.shipment_id
                ):
                    result.skipped.append((order_id, "уже отправлен — скидка только до отправки"))
                elif not order.client_price:
                    result.skipped.append((order_id, "нет цены для клиента"))
                else:
                    cut = int(
                        (Decimal(order.client_price) * percent / 100).quantize(
                            Decimal(1), rounding=ROUND_HALF_UP
                        )
                    )
                    if cut <= 0:
                        result.skipped.append((order_id, "скидка меньше 1 ₩"))
                    else:
                        targets.append((order, data, cut))
            if not targets:
                return result
            client = (
                self._ledger.load_client(tx)
                if any(o.charged_amount_krw > 0 for o, _, _ in targets)
                else None
            )
            now = self._clock.now()
            for order, data, cut in targets:
                old_price = order.client_price or 0
                new_price = old_price - cut
                fields: dict[str, Any] = {
                    "client_price": new_price,
                    "discounts": [
                        *(data.get("discounts") or []),
                        {
                            "key": key,
                            "percent": str(percent),
                            "old": old_price,
                            "new": new_price,
                            "at": now,
                            "by": actor.id,
                        },
                    ],
                    "updated_at": now,
                    "updated_by": actor.id,
                }
                if order.purchase_price is not None:
                    fields["profit"] = new_price - order.purchase_price
                refund = min(cut, order.charged_amount_krw)
                if refund > 0:
                    fields["charged_amount_krw"] = order.charged_amount_krw - refund
                self._orders.update(tx, order.id, fields)
                if refund > 0 and client is not None:
                    result.change = self._ledger.apply(
                        tx,
                        client,
                        entry_id=f"order_discount_{order.id}_{key}",
                        type=LedgerType.ORDER_DISCOUNT,
                        amount_krw=refund,
                        actor=actor,
                        now=now,
                        order_id=order.id,
                        comment=f"Скидка {label}",
                    )
                    result.refunded_krw += refund
                self._auditor.record(
                    tx,
                    actor,
                    now,
                    action="order.discount",
                    entity_type="order",
                    entity_id=order.id,
                    before={
                        "client_price": old_price,
                        "charged_amount_krw": order.charged_amount_krw,
                    },
                    after={
                        "client_price": new_price,
                        "percent": str(percent),
                        "refunded_krw": refund,
                    },
                )
                result.updated.append((order.id, old_price, new_price))
            updated_ids = [order_id for order_id, _, _ in result.updated]
            self._events.record(
                tx,
                actor,
                now,
                EventType.ORDER_DISCOUNT,
                f"Скидка {label}: {_ids(updated_ids)}",
                body="\n".join(
                    f"{order_id}: {format_krw(old)} → {format_krw(new)}"
                    for order_id, old, new in result.updated
                ),
                order_ids=updated_ids,
                amount_krw=result.refunded_krw or None,
            )
            return result

        try:
            return self._db.run_transaction(fn)
        except DocumentExistsError:
            raise ConflictError(
                "Эта скидка уже проведена. Обновите данные и проверьте заказы."
            ) from None

    # --- delete ------------------------------------------------------------

    def preview_delete(self, actor: Actor, order_ids: Sequence[str]) -> DeletePreview:
        require_admin(actor)
        ids = list(dict.fromkeys(normalize_order_id(i) for i in order_ids))
        require_bulk_size(ids)
        found = self._orders.get_many(self._db, ids)
        preview = DeletePreview()
        for order_id in ids:
            order = found.get(order_id)
            if order is None:
                preview.not_found.append(order_id)
            else:
                preview.orders.append(order)
        return preview

    def delete_orders(self, actor: Actor, order_ids: Sequence[str]) -> DeleteResult:
        """Remove orders everywhere: the order, its photos, its history events and
        the link to the Telegram message. What was still charged is refunded to
        the balance; ledger entries and audit logs stay (they are never deleted).

        Sent orders can be deleted too (the owner's decision): the order leaves
        its shipment's `order_ids`; the shipment and its delivery charge stay.
        A deleted number is handed out again only from the end and only
        if the order never had money history (see CounterRepository.get_floor).
        """
        require_admin(actor)
        ids = list(dict.fromkeys(normalize_order_id(i) for i in order_ids))
        require_bulk_size(ids)
        photos: list[str] = []

        def fn(tx: Transaction) -> DeleteResult:
            photos.clear()
            result = DeleteResult()
            raw = tx.get_many(self._orders.collection, ids)
            targets: list[tuple[Order, dict[str, Any]]] = []
            for order_id in ids:
                data = raw.get(order_id)
                if data is None:
                    result.not_found.append(order_id)
                    continue
                targets.append((Order.from_doc(order_id, data), data))
            if not targets:
                return result

            deleted_ids = {order.id for order, _ in targets}
            # Read phase: everything below is read before the first write.
            had_money = {
                order.id: self._ledger.has_entry(tx, order_charge_entry_id(order.id))
                for order, _ in targets
            }
            client = (
                self._ledger.load_client(tx)
                if any(order.charged_amount_krw > 0 for order, _ in targets)
                else None
            )
            events: dict[str, Event] = {}
            intake_keys: list[str] = []
            for order, _ in targets:
                for event in self._event_repo.for_order(tx, order.id):
                    events[event.id] = event
                if order.source_chat_id is None or order.source_message_id is None:
                    continue
                key = self._intake.key(order.source_chat_id, order.source_message_id)
                if self._intake.order_id(tx, key) == order.id:
                    intake_keys.append(key)
            shipments = {
                sid: shipment
                for sid in {order.shipment_id for order, _ in targets if order.shipment_id}
                if (shipment := self._shipments.get(tx, sid)) is not None
            }
            all_orders = tx.query(self._orders.collection)
            current_next, floor = self._sequences.read_for_release(tx, ORDER_COUNTER)

            remaining = [(doc_id, d) for doc_id, d in all_orders if doc_id not in deleted_ids]
            used_photos = {
                d.get(name) for _, d in remaining for name in ("photo_url", "thumbnail_url")
            }
            for order, _ in targets:
                photos.extend(
                    url
                    for url in (order.photo_url, order.thumbnail_url)
                    if url and url not in used_photos
                )
            highest_remaining = max(
                (n for n in (order_number(doc_id) for doc_id, _ in remaining) if n is not None),
                default=0,
            )
            burned = [order_number(order_id) or 0 for order_id, spent in had_money.items() if spent]
            new_floor = max([floor, *burned])

            # Write phase.
            now = self._clock.now()
            for order, data in targets:
                self._orders.delete(tx, order.id)
                refund = order.charged_amount_krw
                if refund > 0 and client is not None:
                    result.change = self._ledger.apply(
                        tx,
                        client,
                        entry_id=order_refund_entry_id(order.id),
                        type=LedgerType.ORDER_REFUND,
                        amount_krw=refund,
                        actor=actor,
                        now=now,
                        order_id=order.id,
                        comment=f"Заказ удалён: {order.title}" if order.title else "Заказ удалён",
                    )
                    result.refunds.append((order.id, refund))
                self._auditor.record(
                    tx,
                    actor,
                    now,
                    action="order.delete",
                    entity_type="order",
                    entity_id=order.id,
                    before=data,
                    after={
                        "refunded_krw": refund,
                        "balance_after": result.change.balance_after
                        if refund > 0 and result.change
                        else None,
                    },
                )
                result.deleted.append(order.id)
            for event in events.values():
                left = [i for i in event.order_ids if i not in deleted_ids]
                if left:
                    self._event_repo.set_order_ids(tx, event.id, left)
                else:
                    self._event_repo.delete(tx, event.id)
            for key in intake_keys:
                self._intake.delete(tx, key)
            for sid, shipment in shipments.items():
                left = [i for i in shipment.order_ids if i not in deleted_ids]
                self._shipments.update(tx, sid, {"order_ids": left, "updated_at": now})
            self._events.touched(tx)  # e.g. the photo's reaction in the group goes
            new_next = self._sequences.release(
                tx,
                ORDER_COUNTER,
                current_next=current_next,
                floor=new_floor,
                highest_remaining=highest_remaining,
                now=now,
            )
            result.next_order_id = make_order_id(new_next) if new_next is not None else None
            return result

        try:
            result = self._db.run_transaction(fn)
        except DocumentExistsError:
            raise ConflictError(
                "Возврат по одному из заказов уже есть в истории транзакций. Удаление "
                "остановлено, ничего не изменено — проверьте заказы вручную."
            ) from None
        if self._blobs is not None:
            for url in photos:
                try:
                    self._blobs.delete_url(url)
                except Exception:  # noqa: BLE001 - the order is gone; a stray file is harmless
                    logger.warning("Could not delete photo %s", url, exc_info=True)
        return result

    # --- helpers -----------------------------------------------------------

    def _require_order(self, tx: Transaction, order_id: str) -> Order:
        order = self._orders.get(tx, order_id)
        if order is None:
            raise NotFoundError(f"Заказ {order_id} не найден.")
        if order.status is None:
            raise ConflictError(
                f"У заказа {order_id} неизвестный статус «{order.status_raw}». "
                "Операция остановлена, чтобы не испортить данные."
            )
        return order


def _fmt(amount: int | None) -> str:
    return format_krw(amount) if amount is not None else "—"


def _ids(ids: Sequence[str], limit: int = 6) -> str:
    shown = ", ".join(ids[:limit])
    return f"{shown} и ещё {len(ids) - limit}" if len(ids) > limit else shown


def _describe(order: Order) -> str:
    parts = [order.title or "Заказ", f"размер {order.size}" if order.size else None]
    return " · ".join(p for p in parts if p)


def _purchase(
    purchase_price: int | None,
    client_price: int | None,
    source_url: str | None,
    at: datetime | None,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "purchase_price": purchase_price,
        "client_price": client_price,
        "source_url": source_url,
        "bought_at": at,
        "note": note,
    }


_STATUS_EVENTS = {
    OrderStatus.WAREHOUSE: (EventType.ORDER_WAREHOUSE, "Прибыл на склад"),
    OrderStatus.DELIVERED: (EventType.ORDER_DELIVERED, "Доставлен"),
}

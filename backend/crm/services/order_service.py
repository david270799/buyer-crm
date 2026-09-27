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

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from crm.domain.enums import STATUS_LABELS_RU, LedgerType, OrderStatus
from crm.domain.errors import ConflictError, NotFoundError, ValidationError
from crm.domain.ids import make_order_id, normalize_order_id, order_number
from crm.domain.models import Order, status_timestamp_field
from crm.domain.money import MAX_AMOUNT_KRW, format_krw
from crm.repositories import OrderRepository
from crm.services.common import Actor, Auditor, Clock, require_admin, require_bulk_size
from crm.services.ledger import (
    BalanceChange,
    BalanceLedger,
    order_charge_entry_id,
    order_refund_entry_id,
)
from crm.services.sequences import SequenceAllocator
from crm.storage import Database, DocumentExistsError, Transaction

ORDER_COUNTER = "orders"

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


class OrderService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        orders: OrderRepository,
        ledger: BalanceLedger,
        sequences: SequenceAllocator,
        auditor: Auditor,
    ):
        self._db = db
        self._clock = clock
        self._orders = orders
        self._ledger = ledger
        self._sequences = sequences
        self._auditor = auditor

    # --- reads -------------------------------------------------------------

    def get_order(self, actor: Actor, order_id: str) -> Order:
        """Any role may read; callers must render through crm.domain.views."""
        order_id = normalize_order_id(order_id)
        order = self._orders.get(self._db, order_id)
        if order is None:
            raise NotFoundError(f"Заказ {order_id} не найден.")
        return order

    # --- create ------------------------------------------------------------

    def create_order(self, actor: Actor, new: NewOrder) -> Order:
        require_admin(actor)
        _check_price(new.purchase_price, "Закупочная цена", allow_zero=True)
        _check_price(new.client_price, "Цена для клиента", allow_zero=True)
        fields = {
            "brand": _clean_text(new.brand, "Бренд", _MAX_SHORT_TEXT),
            "model": _clean_text(new.model, "Модель", _MAX_SHORT_TEXT),
            "size": _clean_text(new.size, "Размер", _MAX_SHORT_TEXT),
            "source_url": _clean_text(new.source_url, "Ссылка", _MAX_LONG_TEXT),
            "photo_url": _clean_text(new.photo_url, "Фото", _MAX_LONG_TEXT),
            "thumbnail_url": _clean_text(new.thumbnail_url, "Миниатюра", _MAX_LONG_TEXT),
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
            return Order.from_doc(order_id, data)

        return self._sequences.run(ORDER_COUNTER, self._max_order_number, self._clock.now, fn)

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
                    "Повторное списание не выполняется. Изменение цены после выкупа будет "
                    "отдельной операцией с корректировкой баланса."
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
                charge_is_explicit=True,
                timestamps={**order.timestamps, "bought_at": now, "updated_at": now},
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
                    f"Заказ {order_id} уже в статусе «{label(order.status)}». Автоматическая "
                    "отмена с возвратом денег для отправленного заказа не выполняется. "
                    "Если возврат нужен — используйте /adjust."
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
                charge_is_explicit=True,
                timestamps={**order.timestamps, "cancelled_at": now, "updated_at": now},
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
        if new_status in _STATUS_HAS_OWN_COMMAND:
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
                elif new_status is OrderStatus.CARGO and not order.shipment_id:
                    result.skipped.append((order_id, "нет отправки — используйте /cargo"))
                elif new_status is OrderStatus.WAREHOUSE and order.shipment_id:
                    result.skipped.append((order_id, f"входит в отправку {order.shipment_id}"))
                else:
                    to_update.append(order)

            now = self._clock.now()
            for order in to_update:
                self._orders.update(
                    tx,
                    order.id,
                    {
                        "status": new_status.value,
                        ts_field: now,
                        "updated_at": now,
                        "updated_by": actor.id,
                        **order.legacy_charge_fields(),
                    },
                )
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
            return result

        return self._db.run_transaction(fn)

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

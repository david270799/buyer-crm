"""Shipments: one physical parcel with several orders.

`ship_orders` is the single entry point used by `/cargo` today and by the
Mini App / dashboard "Создать отправку" form later. In one transaction it
creates the shipment (or extends the existing one with the same tracking
code), and marks every accepted order `cargo` with `shipment_id` and
`cargo_code`.

A transaction is used instead of a plain batch write because each order has
to be validated against its current state; the commit is still atomic.

Shipping cost is only stored on the shipment. It is NOT charged to the
client balance (see "Открытые вопросы" in docs/architecture.md).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from crm.domain.enums import OrderStatus
from crm.domain.errors import ConflictError, NotFoundError, ValidationError
from crm.domain.ids import make_shipment_id, normalize_order_id, normalize_tracking_code
from crm.domain.models import Order, Shipment
from crm.domain.money import MAX_AMOUNT_KRW
from crm.domain.timeutil import to_local
from crm.repositories import OrderRepository, ShipmentRepository
from crm.services.common import Actor, Auditor, Clock, require_admin, require_bulk_size
from crm.services.sequences import SequenceAllocator
from crm.storage import Database, Transaction

SHIPMENT_COUNTER = "shipments"
_MAX_TEXT = 2000
_MAX_WEIGHT_KG = 1000


@dataclass
class ShipmentDetails:
    box_number: str | None = None
    weight_kg: float | None = None
    shipping_cost_krw: int | None = None
    shipment_date: datetime | None = None
    comment: str | None = None
    photo_url: str | None = None


@dataclass
class ShipResult:
    shipment: Shipment | None
    created: bool = False
    added: list[str] = field(default_factory=list)
    already_in_shipment: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def _validate_details(details: ShipmentDetails) -> dict:
    if details.weight_kg is not None and not (0 < details.weight_kg <= _MAX_WEIGHT_KG):
        raise ValidationError(f"Вес должен быть больше 0 и не больше {_MAX_WEIGHT_KG} кг.")
    cost = details.shipping_cost_krw
    if cost is not None and (isinstance(cost, bool) or cost < 0 or cost > MAX_AMOUNT_KRW):
        raise ValidationError("Некорректная стоимость доставки.")
    for name, value in (("Комментарий", details.comment), ("Номер коробки", details.box_number)):
        if value is not None and len(value) > _MAX_TEXT:
            raise ValidationError(f"Поле «{name}» слишком длинное.")
    return {
        "box_number": (details.box_number or "").strip() or None,
        "weight_kg": details.weight_kg,
        "shipping_cost_krw": cost,
        "shipment_date": details.shipment_date,
        "comment": (details.comment or "").strip() or None,
        "photo_url": details.photo_url,
    }


class ShipmentService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        orders: OrderRepository,
        shipments: ShipmentRepository,
        sequences: SequenceAllocator,
        auditor: Auditor,
    ):
        self._db = db
        self._clock = clock
        self._orders = orders
        self._shipments = shipments
        self._sequences = sequences
        self._auditor = auditor

    def get_shipment(self, actor: Actor, shipment_id: str) -> tuple[Shipment, list[Order]]:
        shipment = self._shipments.get(self._db, shipment_id.strip().upper())
        if shipment is None:
            raise NotFoundError(f"Отправка {shipment_id} не найдена.")
        orders = self._orders.get_many(self._db, shipment.order_ids)
        return shipment, [order for order in orders.values() if order is not None]

    def list_shipments(self, actor: Actor, limit: int = 20) -> list[Shipment]:
        return self._shipments.list_recent(self._db, limit=limit)

    def ship_orders(
        self,
        actor: Actor,
        order_ids: Sequence[str],
        tracking_code: str | None,
        details: ShipmentDetails | None = None,
    ) -> ShipResult:
        require_admin(actor)
        code = normalize_tracking_code(tracking_code) if tracking_code else None
        ids = list(dict.fromkeys(normalize_order_id(i) for i in order_ids))
        require_bulk_size(ids)
        detail_fields = _validate_details(details or ShipmentDetails())

        def fn(tx: Transaction) -> ShipResult:
            existing = self._shipments.find_by_tracking(tx, code) if code else []
            if len(existing) > 1:
                raise ConflictError(
                    f"Трек-номер {code} найден в нескольких отправках: "
                    f"{', '.join(s.id for s in existing)}. Исправьте данные вручную."
                )
            target = existing[0] if existing else None
            orders = self._orders.get_many(tx, ids)

            result = ShipResult(shipment=target)
            to_add: list[Order] = []
            for order_id in ids:
                order = orders[order_id]
                if order is None:
                    result.not_found.append(order_id)
                elif target is not None and order.shipment_id == target.id:
                    result.already_in_shipment.append(order_id)
                elif order.shipment_id:
                    result.skipped.append((order_id, f"уже в отправке {order.shipment_id}"))
                elif order.status is None:
                    result.skipped.append((order_id, f"неизвестный статус «{order.status_raw}»"))
                elif order.status is OrderStatus.NEW:
                    result.skipped.append((order_id, "не выкуплен — сначала /buy"))
                elif order.status is OrderStatus.CANCELLED:
                    result.skipped.append((order_id, "отменён"))
                elif order.status is OrderStatus.DELIVERED:
                    result.skipped.append((order_id, "уже доставлен"))
                else:
                    to_add.append(order)

            if not to_add:
                return result

            now = self._clock.now()
            number: int | None = None
            if target is None:
                year = to_local(now).year
                number = self._sequences.reserve(
                    tx,
                    SHIPMENT_COUNTER,
                    lambda n: self._shipments.exists(tx, make_shipment_id(year, n)),
                )
                shipment_id = make_shipment_id(year, number)
            else:
                shipment_id = target.id

            # --- writes ---
            added_ids = [order.id for order in to_add]
            if target is None:
                assert number is not None
                data = {
                    "shipment_id": shipment_id,
                    "shipment_number": number,
                    "tracking_code": code,
                    **detail_fields,
                    "order_ids": added_ids,
                    "created_at": now,
                    "created_by": actor.id,
                    "updated_at": now,
                    "updated_by": actor.id,
                }
                self._shipments.create(tx, shipment_id, data)
                self._sequences.commit(tx, SHIPMENT_COUNTER, number, now)
                self._auditor.record(
                    tx,
                    actor,
                    now,
                    action="shipment.create",
                    entity_type="shipment",
                    entity_id=shipment_id,
                    before=None,
                    after={"tracking_code": code, "order_ids": added_ids},
                )
                result.shipment = Shipment.from_doc(shipment_id, data)
                result.created = True
            else:
                merged = list(dict.fromkeys([*target.order_ids, *added_ids]))
                self._shipments.update(
                    tx,
                    shipment_id,
                    {"order_ids": merged, "updated_at": now, "updated_by": actor.id},
                )
                self._auditor.record(
                    tx,
                    actor,
                    now,
                    action="shipment.add_orders",
                    entity_type="shipment",
                    entity_id=shipment_id,
                    before={"order_ids": target.order_ids},
                    after={"order_ids": merged},
                )
                target.order_ids = merged
                result.shipment = target

            for order in to_add:
                fields = {
                    "status": OrderStatus.CARGO.value,
                    "shipment_id": shipment_id,
                    "cargo_at": now,
                    "updated_at": now,
                    "updated_by": actor.id,
                    **order.legacy_charge_fields(),
                }
                if code:
                    fields["cargo_code"] = code
                self._orders.update(tx, order.id, fields)
                self._auditor.record(
                    tx,
                    actor,
                    now,
                    action="order.ship",
                    entity_type="order",
                    entity_id=order.id,
                    before={"status": order.status_raw, "cargo_code": order.cargo_code},
                    after={
                        "status": OrderStatus.CARGO.value,
                        "shipment_id": shipment_id,
                        "cargo_code": code,
                    },
                )
            result.added = added_ids
            return result

        return self._sequences.run(
            SHIPMENT_COUNTER,
            lambda: self._shipments.max_shipment_number(self._db),
            self._clock.now,
            fn,
        )

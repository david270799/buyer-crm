"""Shipments: one physical parcel with several orders.

`ship_orders` is the single entry point used by `/cargo` and by the Mini App
"Создать отправку" form. In one transaction it creates the shipment (or
extends the existing one with the same tracking code), marks every accepted
order `cargo` with `shipment_id` and `cargo_code`, and charges the shipping
cost to the client balance.

A transaction is used instead of a plain batch write because each order has
to be validated against its current state; the commit is still atomic.

Shipping money rules (same idea as orders):
* `shipping_charged_krw` on the shipment is what is currently charged;
* setting a cost charges only the difference to it, so saving the same cost
  twice moves nothing, and lowering the cost refunds the difference;
* every movement is a `shipping_charge` ledger entry with a deterministic ID
  `shipping_charge_<shipment>_<n>`, written with `create`.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any

from crm.domain.enums import LedgerType, OrderStatus
from crm.domain.errors import ConflictError, NotFoundError, ValidationError
from crm.domain.events import EventType
from crm.domain.ids import make_shipment_id, normalize_order_id, normalize_tracking_code
from crm.domain.models import ClientInfo, Order, Shipment
from crm.domain.money import MAX_AMOUNT_KRW, format_krw
from crm.domain.timeutil import format_date, to_local
from crm.repositories import OrderRepository, ShipmentRepository
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
from crm.services.ledger import BalanceChange, BalanceLedger
from crm.services.sequences import SequenceAllocator
from crm.storage import Database, DocumentExistsError, Transaction

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
    thumbnail_url: str | None = None
    # Several photos: [{"photo_url", "thumbnail_url"}]; the first also fills
    # photo_url / thumbnail_url (lists, bot and older code use those).
    photos: list[dict[str, Any]] | None = None


@dataclass
class ShipmentUpdate:
    """Partial update: fields left as UNSET are not touched, None clears a field."""

    tracking_code: str | None = UNSET
    box_number: str | None = UNSET
    weight_kg: float | None = UNSET
    shipping_cost_krw: int | None = UNSET
    shipment_date: datetime | None = UNSET
    comment: str | None = UNSET
    photo_url: str | None = UNSET
    thumbnail_url: str | None = UNSET
    photos: list[dict[str, Any]] | None = UNSET

    def provided(self) -> dict[str, Any]:
        return provided_fields(self)


@dataclass
class ShipResult:
    shipment: Shipment | None
    created: bool = False
    added: list[str] = field(default_factory=list)
    already_in_shipment: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    shipping_change: BalanceChange | None = None


@dataclass
class ShipmentUpdateResult:
    shipment: Shipment
    shipping_change: BalanceChange | None = None


def _clean_text(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if len(value) > _MAX_TEXT:
        raise ValidationError(f"Поле «{name}» слишком длинное.")
    return value.strip() or None


def _validate_fields(values: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for name, value in values.items():
        if name == "weight_kg":
            if value is not None and not (0 < float(value) <= _MAX_WEIGHT_KG):
                raise ValidationError(f"Вес должен быть больше 0 и не больше {_MAX_WEIGHT_KG} кг.")
            cleaned[name] = float(value) if value is not None else None
        elif name == "shipping_cost_krw":
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value > MAX_AMOUNT_KRW
            ):
                raise ValidationError("Стоимость доставки должна быть целой суммой в вонах ≥ 0.")
            cleaned[name] = value
        elif name == "tracking_code":
            cleaned[name] = normalize_tracking_code(value) if value else None
        elif name == "box_number":
            cleaned[name] = _clean_text(value, "Номер коробки")
        elif name == "comment":
            cleaned[name] = _clean_text(value, "Комментарий")
        elif name in ("photo_url", "thumbnail_url"):
            cleaned[name] = _clean_text(value, "Фото")
        elif name == "photos":
            cleaned[name] = _clean_photos(value) if value is not None else None
        elif name == "shipment_date":
            if value is not None and not isinstance(value, datetime):
                raise ValidationError("Некорректная дата отправки.")
            cleaned[name] = value
        else:  # pragma: no cover - programming error
            raise ValueError(f"Unknown shipment field {name}")
    if cleaned.get("photos") is not None:
        first = cleaned["photos"][0] if cleaned["photos"] else {}
        cleaned["photo_url"] = first.get("photo_url")
        cleaned["thumbnail_url"] = first.get("thumbnail_url")
    elif "photo_url" in cleaned and cleaned.get("photo_url") is not None:
        # A single photo set the old way replaces the whole list.
        url = cleaned["photo_url"]
        cleaned["photos"] = (
            [{"photo_url": url, "thumbnail_url": cleaned.get("thumbnail_url")}] if url else []
        )
    return cleaned


def _clean_photos(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValidationError("Некорректный список фото.")
    if len(value) > MAX_SHIPMENT_PHOTOS:
        raise ValidationError(f"У отправки может быть не больше {MAX_SHIPMENT_PHOTOS} фото.")
    photos = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("photo_url"), str):
            raise ValidationError("Некорректное фото в списке.")
        thumb = item.get("thumbnail_url")
        photos.append(
            {
                "photo_url": _clean_text(item["photo_url"], "Фото"),
                "thumbnail_url": _clean_text(thumb, "Фото") if isinstance(thumb, str) else None,
            }
        )
    return [p for p in photos if p["photo_url"]]


def _details_fields(details: ShipmentDetails) -> dict[str, Any]:
    return _validate_fields({f.name: getattr(details, f.name) for f in fields(details)})


MAX_SHIPMENT_PHOTOS = 10


def shipping_entry_id(shipment_id: str, seq: int) -> str:
    return f"shipping_charge_{shipment_id}_{seq}"


class ShipmentService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        orders: OrderRepository,
        shipments: ShipmentRepository,
        sequences: SequenceAllocator,
        ledger: BalanceLedger,
        auditor: Auditor,
        events: EventRecorder,
    ):
        self._db = db
        self._clock = clock
        self._orders = orders
        self._shipments = shipments
        self._sequences = sequences
        self._ledger = ledger
        self._auditor = auditor
        self._events = events

    # --- reads -------------------------------------------------------------

    def resolve_id(self, reference: str) -> str:
        """`SHP-2026-018`, `18` or `#18` → shipment document ID."""
        ref = reference.strip().upper()
        number = ref.lstrip("#")
        if number.isdigit():
            found = self._shipments.find_by_number(self._db, int(number))
            if found is None:
                raise NotFoundError(f"Отправка #{number} не найдена.")
            return found.id
        return ref

    def get_shipment(self, actor: Actor, shipment_id: str) -> tuple[Shipment, list[Order]]:
        shipment_id = self.resolve_id(shipment_id)
        shipment = self._shipments.get(self._db, shipment_id)
        if shipment is None:
            raise NotFoundError(f"Отправка {shipment_id} не найдена.")
        orders = self._orders.get_many(self._db, shipment.order_ids)
        return shipment, [orders[i] for i in shipment.order_ids if orders.get(i) is not None]

    def list_shipments(self, actor: Actor, limit: int = 20) -> list[Shipment]:
        return self._shipments.list_recent(self._db, limit=max(1, min(limit, 200)))

    def delivered_ids(self, shipments: Sequence[Shipment]) -> set[str]:
        """Shipments whose every order is delivered («Доставлена»); the rest are «В пути»."""
        orders = self._orders.get_many(self._db, [i for s in shipments for i in s.order_ids])
        done: set[str] = set()
        for shipment in shipments:
            found = [orders.get(i) for i in shipment.order_ids]
            found = [o for o in found if o is not None]
            if found and all(o.status is OrderStatus.DELIVERED for o in found):
                done.add(shipment.id)
        return done

    # --- split -----------------------------------------------------------------

    def split_shipment(
        self,
        actor: Actor,
        shipment_id: str,
        order_ids: Sequence[str],
        tracking_code: str | None = None,
    ) -> Shipment:
        """The cargo sent part of a shipment separately: move `order_ids` into a
        new shipment (its own number, tracking code, photos and status).

        No money moves: the shipping cost stays on the original shipment; the
        new one starts at 0 and its cost is set by editing it (difference rule).
        Order statuses do not change.
        """
        require_admin(actor)
        shipment_id = self.resolve_id(shipment_id)
        code = normalize_tracking_code(tracking_code) if tracking_code else None
        ids = list(dict.fromkeys(normalize_order_id(i) for i in order_ids))
        require_bulk_size(ids)
        if not ids:
            raise ValidationError("Выберите заказы, которые ушли отдельной частью.")

        def fn(tx: Transaction) -> Shipment:
            source = self._shipments.get(tx, shipment_id)
            if source is None:
                raise NotFoundError(f"Отправка {shipment_id} не найдена.")
            if code and self._shipments.find_by_tracking(tx, code):
                raise ConflictError(f"Трек-номер {code} уже есть у другой отправки.")
            foreign = [i for i in ids if i not in source.order_ids]
            if foreign:
                raise ValidationError(f"Этих заказов нет в отправке: {', '.join(foreign)}.")
            remaining = [i for i in source.order_ids if i not in ids]
            if not remaining:
                raise ValidationError(
                    "Нельзя перенести все заказы: в отправке должен остаться хотя бы один."
                )
            orders = self._orders.get_many(tx, ids)

            now = self._clock.now()
            year = to_local(now).year
            number = self._sequences.reserve(
                tx,
                SHIPMENT_COUNTER,
                lambda n: self._shipments.exists(tx, make_shipment_id(year, n)),
            )
            new_id = make_shipment_id(year, number)
            data = {
                "shipment_id": new_id,
                "shipment_number": number,
                "tracking_code": code,
                "box_number": None,
                "weight_kg": None,
                "shipping_cost_krw": None,
                "shipment_date": source.shipment_date or now,
                "comment": f"Часть отправки {source.tracking_code or source.shipment_number}",
                "photo_url": None,
                "thumbnail_url": None,
                "photos": [],
                "shipping_charged_krw": 0,
                "shipping_charge_seq": 0,
                "split_from": source.id,
                "order_ids": ids,
                "created_at": now,
                "created_by": actor.id,
                "updated_at": now,
                "updated_by": actor.id,
            }
            self._shipments.create(tx, new_id, data)
            self._sequences.commit(tx, SHIPMENT_COUNTER, number, now)
            self._shipments.update(
                tx,
                source.id,
                {"order_ids": remaining, "updated_at": now, "updated_by": actor.id},
            )
            for order_id in ids:
                order = orders[order_id]
                if order is None:
                    continue
                fields_: dict[str, Any] = {
                    "shipment_id": new_id,
                    "updated_at": now,
                    "updated_by": actor.id,
                }
                if code:
                    fields_["cargo_code"] = code
                self._orders.update(tx, order_id, fields_)
            self._auditor.record(
                tx,
                actor,
                now,
                action="shipment.split",
                entity_type="shipment",
                entity_id=source.id,
                before={"order_ids": source.order_ids},
                after={"order_ids": remaining, "new_shipment": new_id, "moved": ids},
            )
            lines = [f"{_items(len(ids))}: {', '.join(ids)}"]
            if code:
                lines.append(f"Трек-номер: {code}")
            self._events.record(
                tx,
                actor,
                now,
                EventType.SHIPMENT_UPDATED,
                f"Отправка {source.tracking_code or source.shipment_number} разделена: "
                "часть заказов едет отдельно",
                body="\n".join(lines),
                order_ids=ids,
                shipment_id=new_id,
            )
            return Shipment.from_doc(new_id, data)

        return self._sequences.run(
            SHIPMENT_COUNTER,
            lambda: self._shipments.max_shipment_number(self._db),
            self._clock.now,
            fn,
        )

    # --- create / extend -----------------------------------------------------

    def ship_orders(
        self,
        actor: Actor,
        order_ids: Sequence[str],
        tracking_code: str | None,
        details: ShipmentDetails | None = None,
    ) -> ShipResult:
        """Create a shipment (or add orders to the one with this tracking code).

        For an existing shipment only the details that are not None are
        applied; a new shipping cost there charges the difference.
        """
        require_admin(actor)
        code = normalize_tracking_code(tracking_code) if tracking_code else None
        ids = list(dict.fromkeys(normalize_order_id(i) for i in order_ids))
        require_bulk_size(ids)
        detail_fields = _details_fields(details or ShipmentDetails())

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
                charged_before, seq = 0, 0
                new_cost = detail_fields["shipping_cost_krw"]
            else:
                shipment_id = target.id
                charged_before, seq = target.shipping_charged_krw, target.shipping_charge_seq
                new_cost = detail_fields["shipping_cost_krw"]
            delta = (new_cost or 0) - charged_before if new_cost is not None else 0
            client = self._ledger.load_client(tx) if delta else None

            # --- writes ---
            added_ids = [order.id for order in to_add]
            charge_fields: dict[str, Any] = {}
            if client is not None:
                result.shipping_change = self._charge_shipping(
                    tx, client, actor, now, shipment_id, seq + 1, delta, new_cost or 0
                )
                charge_fields = {
                    "shipping_charged_krw": charged_before + delta,
                    "shipping_charge_seq": seq + 1,
                }

            if target is None:
                assert number is not None
                data = {
                    "shipment_id": shipment_id,
                    "shipment_number": number,
                    "tracking_code": code,
                    **detail_fields,
                    "shipping_charged_krw": 0,
                    "shipping_charge_seq": 0,
                    **charge_fields,
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
                    after={
                        "tracking_code": code,
                        "order_ids": added_ids,
                        "shipping_cost_krw": detail_fields["shipping_cost_krw"],
                    },
                )
                result.shipment = Shipment.from_doc(shipment_id, data)
                result.created = True
            else:
                merged = list(dict.fromkeys([*target.order_ids, *added_ids]))
                provided = {k: v for k, v in detail_fields.items() if v is not None}
                self._shipments.update(
                    tx,
                    shipment_id,
                    {
                        **provided,
                        **charge_fields,
                        "order_ids": merged,
                        "updated_at": now,
                        "updated_by": actor.id,
                    },
                )
                self._auditor.record(
                    tx,
                    actor,
                    now,
                    action="shipment.add_orders",
                    entity_type="shipment",
                    entity_id=shipment_id,
                    before={"order_ids": target.order_ids},
                    after={"order_ids": merged, **provided},
                )
                raw = {
                    **_shipment_doc(target),
                    **provided,
                    **charge_fields,
                    "order_ids": merged,
                    "updated_at": now,
                }
                result.shipment = Shipment.from_doc(shipment_id, raw)

            for order in to_add:
                order_fields = {
                    "status": OrderStatus.CARGO.value,
                    "shipment_id": shipment_id,
                    "cargo_at": now,
                    "updated_at": now,
                    "updated_by": actor.id,
                }
                if code:
                    order_fields["cargo_code"] = code
                self._orders.update(tx, order.id, order_fields)
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
            assert result.shipment is not None
            number = result.shipment.shipment_number
            lines = [f"{_items(len(added_ids))}: {', '.join(added_ids)}"]
            if code:
                lines.append(f"Трек-номер: {code}")
            if result.shipping_change:
                lines.append(f"Доставка: {format_krw(new_cost or 0)}")
            self._events.record(
                tx,
                actor,
                now,
                EventType.SHIPMENT_SENT,
                f"Отправка #{number} отправлена"
                if result.created
                else f"Добавлено в отправку #{number}",
                body="\n".join(lines),
                order_ids=added_ids,
                shipment_id=shipment_id,
                amount_krw=result.shipping_change.amount_krw if result.shipping_change else None,
            )
            return result

        try:
            return self._sequences.run(
                SHIPMENT_COUNTER,
                lambda: self._shipments.max_shipment_number(self._db),
                self._clock.now,
                fn,
            )
        except DocumentExistsError:
            raise _duplicate_charge_error() from None

    # --- edit ----------------------------------------------------------------

    def update_shipment(
        self, actor: Actor, shipment_id: str, update: ShipmentUpdate
    ) -> ShipmentUpdateResult:
        require_admin(actor)
        changes = _validate_fields(update.provided())
        if not changes:
            raise ValidationError("Нет изменений.")
        shipment_id = self.resolve_id(shipment_id)

        def fn(tx: Transaction) -> ShipmentUpdateResult:
            shipment = self._shipments.get(tx, shipment_id)
            if shipment is None:
                raise NotFoundError(f"Отправка {shipment_id} не найдена.")

            tracking_changed = (
                "tracking_code" in changes and changes["tracking_code"] != shipment.tracking_code
            )
            if tracking_changed and changes["tracking_code"]:
                clash = [
                    s
                    for s in self._shipments.find_by_tracking(tx, changes["tracking_code"])
                    if s.id != shipment_id
                ]
                if clash:
                    raise ConflictError(
                        f"Трек-номер {changes['tracking_code']} уже есть в отправке {clash[0].id}."
                    )
            orders = self._orders.get_many(tx, shipment.order_ids) if tracking_changed else {}

            delta = 0
            if "shipping_cost_krw" in changes:
                delta = (changes["shipping_cost_krw"] or 0) - shipment.shipping_charged_krw
            client = self._ledger.load_client(tx) if delta else None

            # --- writes ---
            now = self._clock.now()
            doc_changes: dict[str, Any] = {**changes, "updated_at": now, "updated_by": actor.id}
            change = None
            if client is not None:
                seq = shipment.shipping_charge_seq + 1
                change = self._charge_shipping(
                    tx,
                    client,
                    actor,
                    now,
                    shipment_id,
                    seq,
                    delta,
                    changes["shipping_cost_krw"] or 0,
                )
                doc_changes["shipping_charged_krw"] = shipment.shipping_charged_krw + delta
                doc_changes["shipping_charge_seq"] = seq
            self._shipments.update(tx, shipment_id, doc_changes)

            for order_id, order in orders.items():
                if order is not None:
                    self._orders.update(
                        tx,
                        order_id,
                        {
                            "cargo_code": changes["tracking_code"],
                            "updated_at": now,
                            "updated_by": actor.id,
                        },
                    )
            before = _shipment_doc(shipment)
            self._auditor.record(
                tx,
                actor,
                now,
                action="shipment.update",
                entity_type="shipment",
                entity_id=shipment_id,
                before={key: before.get(key) for key in changes},
                after=changes,
            )
            updated = Shipment.from_doc(shipment_id, {**before, **doc_changes})
            self._record_update_events(tx, actor, now, shipment, updated, changes, change)
            return ShipmentUpdateResult(shipment=updated, shipping_change=change)

        try:
            return self._db.run_transaction(fn)
        except DocumentExistsError:
            raise _duplicate_charge_error() from None

    # --- helpers -------------------------------------------------------------

    def _record_update_events(
        self,
        tx: Transaction,
        actor: Actor,
        now: datetime,
        old: Shipment,
        new: Shipment,
        changes: dict[str, Any],
        change: BalanceChange | None,
    ) -> None:
        name = f"#{old.shipment_number}" if old.shipment_number else old.id
        ids = list(old.order_ids)
        if change is not None:
            self._events.record(
                tx,
                actor,
                now,
                EventType.SHIPPING_COST,
                f"Стоимость доставки отправки {name} изменена",
                body=f"{format_krw(old.shipping_cost_krw or 0)} → "
                f"{format_krw(new.shipping_cost_krw or 0)}",
                order_ids=ids,
                shipment_id=old.id,
                amount_krw=change.amount_krw,
            )
        lines = []
        if (
            "tracking_code" in changes
            and new.tracking_code != old.tracking_code
            and new.tracking_code
        ):
            lines.append(f"Трек-номер: {new.tracking_code}")
        if "comment" in changes and new.comment and new.comment != old.comment:
            lines.append(new.comment)
        if "photo_url" in changes and new.photo_url and new.photo_url != old.photo_url:
            lines.append("Добавлено фото отправки")
        if (
            "shipment_date" in changes
            and new.shipment_date
            and new.shipment_date != old.shipment_date
        ):
            lines.append(f"Дата отправки: {format_date(new.shipment_date)}")
        if lines:
            self._events.record(
                tx,
                actor,
                now,
                EventType.SHIPMENT_UPDATED,
                f"Отправка {name} обновлена",
                body="\n".join(lines),
                order_ids=ids,
                shipment_id=old.id,
            )

    def _charge_shipping(
        self,
        tx: Transaction,
        client: ClientInfo,
        actor: Actor,
        now: datetime,
        shipment_id: str,
        seq: int,
        delta: int,
        new_cost: int,
    ) -> BalanceChange:
        comment = (
            f"Доставка {shipment_id}"
            if seq == 1
            else f"Доставка {shipment_id}: стоимость изменена на {format_krw(new_cost)}"
        )
        return self._ledger.apply(
            tx,
            client,
            entry_id=shipping_entry_id(shipment_id, seq),
            type=LedgerType.SHIPPING_CHARGE,
            amount_krw=-delta,
            actor=actor,
            now=now,
            shipment_id=shipment_id,
            comment=comment,
        )


def _shipment_doc(shipment: Shipment) -> dict[str, Any]:
    return {
        "shipment_id": shipment.id,
        "shipment_number": shipment.shipment_number,
        "tracking_code": shipment.tracking_code,
        "box_number": shipment.box_number,
        "weight_kg": shipment.weight_kg,
        "shipping_cost_krw": shipment.shipping_cost_krw,
        "shipment_date": shipment.shipment_date,
        "photo_url": shipment.photo_url,
        "thumbnail_url": shipment.thumbnail_url,
        "photos": [dict(p) for p in shipment.photos],
        "order_ids": shipment.order_ids,
        "comment": shipment.comment,
        "created_at": shipment.created_at,
        "created_by": shipment.created_by,
        "shipping_charged_krw": shipment.shipping_charged_krw,
        "shipping_charge_seq": shipment.shipping_charge_seq,
        "updated_at": shipment.updated_at,
    }


def _duplicate_charge_error() -> ConflictError:
    return ConflictError(
        "Списание за эту доставку уже есть в истории транзакций. "
        "Повторное списание заблокировано — проверьте отправку вручную."
    )


def _items(count: int) -> str:
    mod10, mod100 = count % 10, count % 100
    word = (
        "товар"
        if mod10 == 1 and mod100 != 11
        else "товара"
        if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14
        else "товаров"
    )
    return f"{count} {word}"

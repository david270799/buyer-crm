"""FastAPI app for the Mini App (client and admin) — thin layer over services.

Authentication: every request carries `Authorization: tma <initData>`.
The signature is checked server-side (crm.api.telegram_auth), then the role
comes from RoleResolver (admins from env, the client from Firestore).

* Client endpoints are read-only; everything that changes data requires ADMIN
  (checked here and again inside the services).
* Responses are built only from crm.domain.views, so the client never gets
  purchase prices, profit or internal comments.
* Handlers are plain `def`: FastAPI runs them in a thread pool, which suits
  the synchronous Firestore client.
"""

import logging
import mimetypes
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as dtime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from crm.api.telegram_auth import InitDataError, TelegramUser, validate_init_data
from crm.domain.enums import STATUS_LABELS_RU, Role, parse_status
from crm.domain.errors import (
    ConfigurationError,
    ConflictError,
    CRMError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from crm.domain.events import Event
from crm.domain.models import LedgerEntry, Order, ProfitEntry
from crm.domain.notifications import NotificationSettings
from crm.domain.timeutil import BUSINESS_TZ
from crm.domain.views import ledger_view, order_view, shipment_view
from crm.services.common import Actor
from crm.services.container import Services
from crm.services.ledger import BalanceChange
from crm.services.order_service import BulkUpdate, NewOrder, OrderQuery, OrderUpdate
from crm.services.shipment_service import ShipmentDetails, ShipmentUpdate
from crm.storage import TransactionContentionError

logger = logging.getLogger(__name__)

# Slim containers have no /etc/mime.types; with `nosniff` a wrong type could
# stop browsers from showing local (demo) photos.
mimetypes.add_type("image/webp", ".webp")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
IdempotencyKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{8,80}$")]
OrderIds = Annotated[list[str], Field(min_length=1, max_length=100)]


@dataclass(frozen=True)
class ApiConfig:
    bot_token: str | None
    init_data_max_age_seconds: int = 24 * 3600
    web_origins: tuple[str, ...] = ()
    # Demo mode only: `Authorization: demo admin|client` without Telegram.
    demo: bool = False
    demo_admin_id: int | None = None
    demo_client_id: int | None = None
    static_dir: Path | None = None
    media_dir: Path | None = None
    # The bot (and with it the notification sender) runs in this process.
    bot_running: bool = False


@dataclass(frozen=True)
class Principal:
    actor: Actor
    role: Role
    user: TelegramUser


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


_ERROR_STATUS: list[tuple[type[CRMError], int]] = [
    (NotFoundError, 404),
    (ValidationError, 422),
    (ConflictError, 409),
    (PermissionDeniedError, 403),
    (ConfigurationError, 500),
]


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


# --- request bodies -------------------------------------------------------


class BuyIn(BaseModel):
    purchase_price: int = Field(ge=0)
    client_price: int = Field(gt=0)


class RebuyIn(BaseModel):
    purchase_price: int = Field(ge=0)
    client_price: int = Field(gt=0)
    source_url: str | None = None
    reason: str | None = Field(default=None, max_length=2000)


class NewOrderIn(BaseModel):
    brand: str | None = None
    model: str | None = None
    size: str | None = None
    source_url: str | None = None
    photo_url: str | None = None
    thumbnail_url: str | None = None
    purchase_price: int | None = Field(default=None, ge=0)
    client_price: int | None = Field(default=None, ge=0)
    client_comment: str | None = None
    internal_comment: str | None = None
    attention_required: bool = False
    # Create and immediately /buy (charges client_price once).
    buy_now: bool = False


class OrderPatchIn(BaseModel):
    brand: str | None = None
    model: str | None = None
    size: str | None = None
    source_url: str | None = None
    photo_url: str | None = None
    thumbnail_url: str | None = None
    client_comment: str | None = None
    internal_comment: str | None = None
    attention_required: bool | None = None
    purchase_price: int | None = Field(default=None, ge=0)
    client_price: int | None = Field(default=None, ge=0)


class BulkStatusIn(BaseModel):
    order_ids: OrderIds
    status: str


class RecognizeIn(BaseModel):
    photo_url: str
    text: str | None = None


class PinIn(BaseModel):
    pin: str | None = Field(default=None, max_length=8)


class BulkDiscountIn(BaseModel):
    order_ids: OrderIds
    percent: Decimal = Field(gt=0, lt=100)
    idempotency_key: IdempotencyKey


class BulkDeleteIn(BaseModel):
    order_ids: OrderIds


class BulkUpdateIn(BaseModel):
    order_ids: OrderIds
    client_comment: str | None = None
    internal_comment: str | None = None
    attention_required: bool | None = None


class PhotoIn(BaseModel):
    photo_url: str
    thumbnail_url: str | None = None


class ShipmentIn(BaseModel):
    order_ids: OrderIds
    tracking_code: str | None = None
    box_number: str | None = None
    weight_kg: float | None = Field(default=None, gt=0)
    shipping_cost_krw: int | None = Field(default=None, ge=0)
    shipment_date: date | None = None
    comment: str | None = None
    photo_url: str | None = None
    thumbnail_url: str | None = None
    photos: list[PhotoIn] | None = None


class ShipmentSplitIn(BaseModel):
    order_ids: list[str] = Field(min_length=1, max_length=100)
    tracking_code: str | None = Field(default=None, max_length=100)


class ShipmentPatchIn(BaseModel):
    tracking_code: str | None = None
    box_number: str | None = None
    weight_kg: float | None = Field(default=None, gt=0)
    shipping_cost_krw: int | None = Field(default=None, ge=0)
    shipment_date: date | None = None
    comment: str | None = None
    photo_url: str | None = None
    thumbnail_url: str | None = None
    photos: list[PhotoIn] | None = None


class MoneyIn(BaseModel):
    amount_krw: int
    comment: str | None = None
    idempotency_key: IdempotencyKey


class RateIn(BaseModel):
    krw_per_usd: Decimal


class NotificationsIn(BaseModel):
    recipient: Literal["off", "admins", "client"] | None = None
    level: Literal["important", "all"] | None = None


# --- serialisation --------------------------------------------------------


def order_json(order: Order, role: Role) -> dict[str, Any]:
    view = order_view(order, role)
    view["title"] = order.title
    view["status_label"] = STATUS_LABELS_RU.get(order.status) if order.status else None
    return view


def event_json(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "type": event.type.value if event.type else None,
        "important": event.important,
        "title": event.title,
        "body": event.body,
        "order_ids": event.order_ids,
        "shipment_id": event.shipment_id,
        "amount_krw": event.amount_krw,
        "created_at": event.created_at,
    }


def change_json(change: BalanceChange | None) -> dict[str, Any] | None:
    if change is None:
        return None
    return {
        "amount_krw": change.amount_krw,
        "balance_before": change.balance_before,
        "balance_after": change.balance_after,
    }


def _local_midnight(value: date | None) -> datetime | None:
    return datetime.combine(value, dtime(0, 0), tzinfo=BUSINESS_TZ) if value else None


def _rate(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


# --- app ------------------------------------------------------------------


def create_app(services: Services, config: ApiConfig, lifespan=None) -> FastAPI:
    app = FastAPI(
        title="Buyer CRM API", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.services = services
    app.state.config = config

    if config.web_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.web_origins),
            allow_methods=["GET", "POST", "PATCH", "PUT"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        path = request.url.path
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif path == "/" or path.endswith(".html"):
            # Always revalidate the page: a cached copy would point at the scripts
            # of an older build, which no longer exist after an update (blank app).
            response.headers["Cache-Control"] = "no-cache"
        elif path.startswith("/assets/") and response.status_code == 200:
            # Build files carry a content hash in their names: safe to keep.
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    # --- errors -----------------------------------------------------------

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(CRMError)
    async def crm_error(_: Request, exc: CRMError):
        status = next((code for cls, code in _ERROR_STATUS if isinstance(exc, cls)), 400)
        return _error(status, type(exc).__name__, exc.user_message)

    @app.exception_handler(TransactionContentionError)
    async def contention(_: Request, exc: TransactionContentionError):
        return _error(
            503, "busy", "Данные сейчас изменяются из другого места. Повторите — это безопасно."
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError):
        return _error(422, "invalid_request", "Проверьте заполнение полей.")

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("Unhandled API error on %s %s", request.method, request.url.path)
        return _error(500, "internal", "Внутренняя ошибка. Подробности записаны в лог.")

    # --- auth -------------------------------------------------------------

    def principal(request: Request) -> Principal:
        scheme, _, value = request.headers.get("authorization", "").partition(" ")
        scheme = scheme.lower()
        if scheme == "tma":
            if not config.bot_token:
                raise ApiError(503, "no_bot_token", "Сервер не настроен: нет BOT_TOKEN.")
            try:
                user = validate_init_data(
                    value.strip(),
                    config.bot_token,
                    max_age_seconds=config.init_data_max_age_seconds,
                )
            except InitDataError as exc:
                logger.info("Rejected initData: %s", exc)
                raise ApiError(
                    401, "unauthorized", "Сессия недействительна. Откройте Mini App заново."
                ) from None
        elif scheme == "demo" and config.demo:
            wanted = value.strip().lower()
            user_id = config.demo_admin_id if wanted == "admin" else config.demo_client_id
            if user_id is None:
                raise ApiError(401, "unauthorized", "Демо-пользователь не настроен.")
            user = TelegramUser(id=user_id, first_name="Демо")
        else:
            raise ApiError(401, "unauthorized", "Откройте CRM из Telegram.")

        role = services.roles.resolve(user.id)
        if role is None:
            raise ApiError(403, "forbidden", "У этого Telegram-аккаунта нет доступа к CRM.")
        return Principal(actor=Actor.mini_app(user.id, role), role=role, user=user)

    def admin(p: Annotated[Principal, Depends(principal)]) -> Principal:
        if p.role is not Role.ADMIN:
            raise ApiError(403, "forbidden", "Доступно только администратору.")
        return p

    Any_ = Annotated[Principal, Depends(principal)]
    Admin = Annotated[Principal, Depends(admin)]

    # --- common (client + admin, read-only) --------------------------------

    @app.get("/api/config")
    def public_config() -> dict[str, Any]:
        return {"demo": config.demo}

    @app.get("/api/me")
    def me(p: Any_) -> dict[str, Any]:
        return {
            "role": p.role.value,
            "user": {"id": p.user.id, "first_name": p.user.first_name, "username": p.user.username},
        }

    @app.get("/api/overview")
    def overview(p: Any_) -> dict[str, Any]:
        balance = services.finance.get_balance(p.actor)
        orders = services.orders.overview(p.actor)
        summary: dict[str, Any] = {
            "status_counts": orders.status_counts,
            "attention_count": orders.attention_count,
            "total": orders.total,
            "active": orders.active,
        }
        if p.role is Role.ADMIN:
            summary["profit_total_krw"] = orders.profit_total_krw
            summary["profit_month_krw"] = orders.profit_month_krw
        usd = balance.balance_usd
        return {
            "balance": {
                "krw": balance.balance_krw,
                "usd": float(usd) if usd is not None else None,
                "krw_per_usd": _rate(balance.krw_per_usd),
            },
            "orders": summary,
            "recent": [order_json(o, p.role) for o in orders.recent],
        }

    @app.get("/api/orders")
    def list_orders(
        p: Any_,
        status: str | None = None,
        q: Annotated[str | None, Query(max_length=100)] = None,
        attention: bool | None = None,
        sort: Literal["newest", "oldest", "price_desc", "price_asc"] = "newest",
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        parsed = parse_status(status) if status else None
        if status and parsed is None:
            raise ValidationError(f"Неизвестный статус: {status}")
        page = services.orders.list_orders(
            p.actor,
            OrderQuery(
                status=parsed, search=q, attention=attention, sort=sort, offset=offset, limit=limit
            ),
        )
        return {"items": [order_json(o, p.role) for o in page.items], "total": page.total}

    @app.get("/api/orders/{order_id}")
    def get_order(order_id: str, p: Any_) -> dict[str, Any]:
        order = services.orders.get_order(p.actor, order_id)
        shipment = None
        if order.shipment_id:
            try:
                found, _ = services.shipments.get_shipment(p.actor, order.shipment_id)
                shipment = shipment_view(found, p.role)
            except NotFoundError:
                shipment = None
        history = [event_json(e) for e in services.events.for_order(p.actor, order.id)]
        return {"order": order_json(order, p.role), "shipment": shipment, "history": history}

    @app.get("/api/shipments")
    def list_shipments(p: Any_, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict[str, Any]:
        items = services.shipments.list_shipments(p.actor, limit=limit)
        delivered = services.shipments.delivered_ids(items)
        return {
            "items": [{**shipment_view(s, p.role), "delivered": s.id in delivered} for s in items]
        }

    @app.get("/api/shipments/{reference}")
    def get_shipment(reference: str, p: Any_) -> dict[str, Any]:
        shipment, orders = services.shipments.get_shipment(p.actor, reference)
        delivered = services.shipments.delivered_ids([shipment])
        return {
            "shipment": {**shipment_view(shipment, p.role), "delivered": bool(delivered)},
            "orders": [order_json(o, p.role) for o in orders],
        }

    @app.get("/api/transactions")
    def transactions(p: Any_, limit: Annotated[int, Query(ge=1, le=100)] = 50) -> dict[str, Any]:
        entries = services.finance.history(p.actor, limit=limit)
        return {"items": _ledger_items(services, p, entries)}

    @app.get("/api/events")
    def list_events(
        p: Any_,
        important: bool = False,
        before: datetime | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 30,
    ) -> dict[str, Any]:
        items = services.events.feed(p.actor, important_only=important, before=before, limit=limit)
        return {"items": [event_json(e) for e in items]}

    @app.get("/api/events/unread")
    def unread_events(p: Any_) -> dict[str, Any]:
        unread = services.events.unread(p.actor)
        return {"important": unread.important, "total": unread.total, "seen_at": unread.seen_at}

    @app.post("/api/events/read")
    def read_events(p: Any_) -> dict[str, bool]:
        services.events.mark_read(p.actor)
        return {"ok": True}

    # --- admin: orders ----------------------------------------------------

    @app.post("/api/orders")
    def create_order(body: NewOrderIn, p: Admin) -> dict[str, Any]:
        fields = body.model_dump(exclude={"buy_now"})
        if body.buy_now and (body.purchase_price is None or not body.client_price):
            raise ValidationError("Для выкупа укажите закупочную цену и цену для клиента.")
        order = services.orders.create_order(p.actor, NewOrder(**fields))
        change = None
        if body.buy_now:
            assert body.purchase_price is not None and body.client_price is not None
            result = services.orders.buy(p.actor, order.id, body.purchase_price, body.client_price)
            order, change = result.order, result.change
        return {"order": order_json(order, p.role), "change": change_json(change)}

    @app.patch("/api/orders/{order_id}")
    def patch_order(order_id: str, body: OrderPatchIn, p: Admin) -> dict[str, Any]:
        order = services.orders.update_details(
            p.actor, order_id, OrderUpdate(**body.model_dump(exclude_unset=True))
        )
        return {"order": order_json(order, p.role)}

    @app.post("/api/orders/{order_id}/buy")
    def buy(order_id: str, body: BuyIn, p: Admin) -> dict[str, Any]:
        result = services.orders.buy(p.actor, order_id, body.purchase_price, body.client_price)
        return {
            "order": order_json(result.order, p.role),
            "already_done": result.already_done,
            "change": change_json(result.change),
        }

    @app.post("/api/orders/{order_id}/rebuy")
    def rebuy(order_id: str, body: RebuyIn, p: Admin) -> dict[str, Any]:
        extra = {"source_url": body.source_url} if "source_url" in body.model_fields_set else {}
        result = services.orders.rebuy(
            p.actor, order_id, body.purchase_price, body.client_price, reason=body.reason, **extra
        )
        return {
            "order": order_json(result.order, p.role),
            "already_done": result.already_done,
            "change": change_json(result.change),
        }

    @app.post("/api/orders/{order_id}/cancel")
    def cancel(order_id: str, p: Admin) -> dict[str, Any]:
        result = services.orders.cancel(p.actor, order_id)
        return {
            "order": order_json(result.order, p.role),
            "already_done": result.already_done,
            "refunded_krw": result.refunded_krw,
            "change": change_json(result.change),
        }

    @app.post("/api/orders/bulk/status")
    def bulk_status(body: BulkStatusIn, p: Admin) -> dict[str, Any]:
        status = parse_status(body.status)
        if status is None:
            raise ValidationError(f"Неизвестный статус: {body.status}")
        return _bulk_json(services.orders.set_status(p.actor, body.order_ids, status))

    @app.post("/api/orders/bulk/update")
    def bulk_update(body: BulkUpdateIn, p: Admin) -> dict[str, Any]:
        fields = body.model_dump(exclude_unset=True, exclude={"order_ids"})
        return _bulk_json(
            services.orders.bulk_update(p.actor, body.order_ids, BulkUpdate(**fields))
        )

    @app.post("/api/orders/bulk/discount")
    def bulk_discount(body: BulkDiscountIn, p: Admin) -> dict[str, Any]:
        result = services.orders.discount(
            p.actor, body.order_ids, body.percent, f"ma-{body.idempotency_key}"
        )
        return {
            "updated": [
                {"order_id": i, "old_price": old, "new_price": new}
                for i, old, new in result.updated
            ],
            "unchanged": result.unchanged,
            "not_found": result.not_found,
            "skipped": [{"order_id": i, "reason": r} for i, r in result.skipped],
            "refunded_krw": result.refunded_krw,
            "change": change_json(result.change),
        }

    @app.post("/api/orders/bulk/delete/preview")
    def bulk_delete_preview(body: BulkDeleteIn, p: Admin) -> dict[str, Any]:
        preview = services.orders.preview_delete(p.actor, body.order_ids)
        return {
            "orders": [order_json(o, p.role) for o in preview.orders],
            "refund_krw": preview.refund_krw,
            "not_found": preview.not_found,
            "skipped": [{"order_id": i, "reason": r} for i, r in preview.skipped],
        }

    @app.post("/api/orders/bulk/delete")
    def bulk_delete(body: BulkDeleteIn, p: Admin) -> dict[str, Any]:
        result = services.orders.delete_orders(p.actor, body.order_ids)
        return {
            "deleted": result.deleted,
            "not_found": result.not_found,
            "skipped": [{"order_id": i, "reason": r} for i, r in result.skipped],
            "refunded_krw": result.refunded_krw,
            "change": change_json(result.change),
            "next_order_id": result.next_order_id,
        }

    # --- admin: shipments -------------------------------------------------

    @app.post("/api/shipments")
    def create_shipment(body: ShipmentIn, p: Admin) -> dict[str, Any]:
        details = ShipmentDetails(
            box_number=body.box_number,
            weight_kg=body.weight_kg,
            shipping_cost_krw=body.shipping_cost_krw,
            shipment_date=_local_midnight(body.shipment_date),
            comment=body.comment,
            photo_url=body.photo_url,
            thumbnail_url=body.thumbnail_url,
            photos=[p.model_dump() for p in body.photos] if body.photos is not None else None,
        )
        result = services.shipments.ship_orders(
            p.actor, body.order_ids, body.tracking_code or None, details
        )
        return {
            "shipment": shipment_view(result.shipment, p.role) if result.shipment else None,
            "created": result.created,
            "added": result.added,
            "already_in_shipment": result.already_in_shipment,
            "not_found": result.not_found,
            "skipped": [{"order_id": i, "reason": r} for i, r in result.skipped],
            "change": change_json(result.shipping_change),
        }

    @app.patch("/api/shipments/{reference}")
    def patch_shipment(reference: str, body: ShipmentPatchIn, p: Admin) -> dict[str, Any]:
        fields = body.model_dump(exclude_unset=True)
        if "shipment_date" in fields:
            fields["shipment_date"] = _local_midnight(fields["shipment_date"])
        result = services.shipments.update_shipment(p.actor, reference, ShipmentUpdate(**fields))
        return {
            "shipment": shipment_view(result.shipment, p.role),
            "change": change_json(result.shipping_change),
        }

    @app.post("/api/shipments/{reference}/split")
    def split_shipment(reference: str, body: ShipmentSplitIn, p: Admin) -> dict[str, Any]:
        shipment = services.shipments.split_shipment(
            p.actor, reference, body.order_ids, body.tracking_code or None
        )
        return {"shipment": shipment_view(shipment, p.role)}

    # --- admin: finance & settings ----------------------------------------

    @app.post("/api/finance/deposit")
    def deposit(body: MoneyIn, p: Admin) -> dict[str, Any]:
        result = services.finance.deposit(
            p.actor, body.amount_krw, body.comment, f"ma-{body.idempotency_key}"
        )
        return {"entry": ledger_view(result.entry, p.role), "already_done": result.already_done}

    @app.post("/api/finance/adjust")
    def adjust(body: MoneyIn, p: Admin) -> dict[str, Any]:
        result = services.finance.adjust(
            p.actor, body.amount_krw, body.comment or "", f"ma-{body.idempotency_key}"
        )
        return {"entry": ledger_view(result.entry, p.role), "already_done": result.already_done}

    @app.get("/api/finance/profit")
    def profit_history(p: Admin) -> dict[str, Any]:
        entries = services.profit.history(p.actor) if services.profit else []
        return {"items": [_profit_json(e) for e in entries]}

    @app.post("/api/finance/profit")
    def add_profit(body: MoneyIn, p: Admin) -> dict[str, Any]:
        if services.profit is None:
            raise ConfigurationError("Учёт прибыли не подключён.")
        result = services.profit.add(
            p.actor, body.amount_krw, body.comment, f"ma-{body.idempotency_key}"
        )
        return {"entry": _profit_json(result.entry), "already_done": result.already_done}

    def notifications_json(actor: Actor, current: NotificationSettings) -> dict[str, Any]:
        return {
            "recipient": current.recipient.value,
            "level": current.level.value,
            "updated_at": current.updated_at,
            "last_sent_at": current.last_sent_at,
            "last_error": current.last_error if current.has_recent_error else None,
            "last_error_at": current.last_error_at if current.has_recent_error else None,
            "client_has_telegram": services.notifications.client_has_telegram(actor),
            "bot_running": config.bot_running,
        }

    @app.get("/api/settings")
    def get_settings(p: Admin) -> dict[str, Any]:
        current = services.finance.get_settings(p.actor)
        return {
            "krw_per_usd": _rate(current.krw_per_usd),
            "updated_at": current.updated_at,
            "uploads_enabled": services.images is not None,
            "recognition_enabled": bool(
                services.photo_recognition and services.photo_recognition.enabled
            ),
            "notifications": notifications_json(
                p.actor, services.notifications.get_settings(p.actor)
            ),
        }

    @app.get("/api/security")
    def security_status(p: Admin) -> dict[str, Any]:
        length = services.security.pin_length(p.actor) if services.security else 0
        return {"pin_set": length > 0, "pin_length": length}

    @app.put("/api/security/pin")
    def security_set_pin(body: PinIn, p: Admin) -> dict[str, Any]:
        if services.security is None:
            raise ConfigurationError("PIN не поддерживается.")
        return {"pin_set": services.security.set_pin(p.actor, body.pin)}

    @app.post("/api/security/unlock")
    def security_unlock(body: PinIn, p: Admin) -> dict[str, Any]:
        if services.security is None:
            return {"ok": True}
        ok = services.security.check(p.actor, body.pin or "")
        if not ok:
            raise ValidationError("Неверный PIN.")
        return {"ok": True}

    @app.put("/api/settings/notifications")
    def set_notifications(body: NotificationsIn, p: Admin) -> dict[str, Any]:
        changes = body.model_dump(exclude_none=True)
        updated = services.notifications.update_settings(p.actor, **changes)
        return notifications_json(p.actor, updated)

    @app.put("/api/settings/rate")
    def set_rate(body: RateIn, p: Admin) -> dict[str, Any]:
        updated = services.finance.set_rate(p.actor, body.krw_per_usd)
        return {"krw_per_usd": _rate(updated.krw_per_usd), "updated_at": updated.updated_at}

    @app.post("/api/recognize")
    def recognize_photo(body: RecognizeIn, p: Admin) -> dict[str, Any]:
        if services.photo_recognition is None:
            raise ConfigurationError("Распознавание не подключено.")
        result = services.photo_recognition.recognize(p.actor, body.photo_url, body.text)
        return {
            "recognized": result.recognized,
            "brand": result.brand,
            "model": result.model,
            "size": result.size,
            "category": result.category,
            "confidence": result.confidence,
            "not_a_product": result.not_a_product,
            "engine": result.engine,
        }

    @app.post("/api/images")
    def upload_image(p: Admin, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        if services.images is None:
            raise ConfigurationError("Хранилище фото не настроено (FIREBASE_STORAGE_BUCKET).")
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValidationError("Файл больше 20 МБ.")
        started = time.monotonic()
        stored = services.images.store(p.actor, data)
        logger.info(
            "Stored image %s KB in %.2fs", stored.photo_bytes // 1024, time.monotonic() - started
        )
        return {
            "photo_url": stored.photo_url,
            "thumbnail_url": stored.thumbnail_url,
            "width": stored.width,
            "height": stored.height,
        }

    # --- static files -----------------------------------------------------

    if config.media_dir is not None:
        app.mount("/media", StaticFiles(directory=config.media_dir), name="media")
    if config.static_dir is not None and (config.static_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=config.static_dir, html=True), name="web")

    return app


def _profit_json(entry: ProfitEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "amount_krw": entry.amount_krw,
        "comment": entry.comment,
        "created_at": entry.created_at,
    }


def _bulk_json(result) -> dict[str, Any]:
    return {
        "updated": result.updated,
        "unchanged": result.unchanged,
        "not_found": result.not_found,
        "skipped": [{"order_id": i, "reason": r} for i, r in result.skipped],
    }


def _ledger_items(
    services: Services, p: Principal, entries: list[LedgerEntry]
) -> list[dict[str, Any]]:
    orders = services.orders.get_orders(p.actor, [e.order_id for e in entries if e.order_id])
    items = []
    for entry in entries:
        view = ledger_view(entry, p.role)
        order = orders.get(entry.order_id) if entry.order_id else None
        view["order"] = (
            {"id": order.id, "title": order.title, "thumbnail_url": order.thumbnail_url}
            if order
            else None
        )
        items.append(view)
    return items

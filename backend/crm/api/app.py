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
import secrets
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
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from crm.api.telegram_auth import InitDataError, TelegramUser, validate_init_data
from crm.domain.categories import category_from_text
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
from crm.domain.models import LedgerEntry, Order, ProfitEntry, ShowcaseItem
from crm.domain.notifications import NotificationSettings
from crm.domain.timeutil import BUSINESS_TZ
from crm.domain.views import ledger_rows, ledger_view, order_view, shipment_view, showcase_view
from crm.services.common import Actor
from crm.services.container import Services
from crm.services.ledger import BalanceChange
from crm.services.order_service import BulkUpdate, NewOrder, OrderQuery, OrderUpdate
from crm.services.shipment_service import ShipmentDetails, ShipmentUpdate
from crm.services.showcase_service import CartLine
from crm.services.sizes import order_sizes
from crm.services.telegram_share import TelegramShare
from crm.storage import TransactionContentionError

logger = logging.getLogger(__name__)

# Slim containers have no /etc/mime.types; with `nosniff` a wrong type could
# stop browsers from showing local (demo) photos.
mimetypes.add_type("image/webp", ".webp")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
SHARE_FILE_TTL = 10 * 60  # seconds a «Скачать» link lives
SHARE_FILE_MAX = 10
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
    preview: bool = False  # the admin looks at the client's view


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
    shop: str | None = None


class ArrivalIn(BaseModel):
    photo_url: str = Field(max_length=500)
    thumbnail_url: str | None = Field(default=None, max_length=500)


class ShowcaseAddIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class ShowcasePatchIn(BaseModel):
    shop_price_krw: int | None = None
    official_price_krw: int | None = None
    client_price_override: int | None = None
    markup_type: Literal["krw", "pct"] | None = None
    markup_value: int | None = None
    brand: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=120)
    shop: str | None = Field(default=None, max_length=60)
    category: str | None = None


class CartLineIn(BaseModel):
    item_id: str = Field(max_length=80)
    size: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=80)


class ShowcaseOrderIn(BaseModel):
    items: list[CartLineIn] = Field(min_length=1, max_length=20)


class ShopsIn(BaseModel):
    names: list[str] = Field(max_length=100)


class RebuyIn(BaseModel):
    purchase_price: int = Field(ge=0)
    client_price: int = Field(gt=0)
    source_url: str | None = None
    shop: str | None = None
    reason: str | None = Field(default=None, max_length=2000)


class NewOrderIn(BaseModel):
    brand: str | None = None
    model: str | None = None
    size: str | None = None
    size_kr: str | None = None
    source_url: str | None = None
    shop: str | None = None
    category: str | None = None
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
    size_kr: str | None = None
    source_url: str | None = None
    shop: str | None = None
    category: str | None = None
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
    watch_count: int | None = Field(default=None, ge=0, le=50)


class LinkIn(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class DuplicateIn(BaseModel):
    count: int = Field(default=1, ge=1, le=10)


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
    watch_count: int | None = Field(default=None, ge=0, le=50)


class MoneyIn(BaseModel):
    amount_krw: int
    comment: str | None = None
    idempotency_key: IdempotencyKey


class RateIn(BaseModel):
    krw_per_usd: Decimal


class NotificationsIn(BaseModel):
    recipient: Literal["off", "admins", "client", "both"] | None = None
    level: Literal["important", "all"] | None = None


# --- serialisation --------------------------------------------------------


def _order_json(order: Order, role: Role) -> dict[str, Any]:
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


def showcase_json(
    item: ShowcaseItem,
    liked: set[str] | frozenset[str] = frozenset(),
    role: Role = Role.ADMIN,
) -> dict[str, Any]:
    """A «Витрина» card; the client's copy goes through domain/views.py."""
    return showcase_view(_showcase_card(item, liked), role)


def _showcase_card(item: ShowcaseItem, liked: set[str] | frozenset[str]) -> dict[str, Any]:
    return {
        "id": item.id,
        "url": item.url,
        "status": item.status,
        "shop": item.shop,
        "brand": item.brand,
        "model": item.model,
        "title": item.title,
        "title_line": item.title_line,
        "category": item.category,
        "photo_url": item.photo_url,
        "thumbnail_url": item.thumbnail_url,
        "photos": item.photos
        or (
            [{"photo_url": item.photo_url, "thumbnail_url": item.thumbnail_url}]
            if item.photo_url
            else []
        ),
        "shop_price_krw": item.shop_price_krw,
        "official_price_krw": item.official_price_krw,
        "official_url": item.official_url,
        "markup_type": item.markup_type,
        "markup_value": item.markup_value,
        "client_price_override": item.client_price_override,
        "client_price_krw": item.client_price_krw,
        "sizes": item.sizes,
        "note": item.note,
        "liked": item.id in (liked or set()),
        "refreshed_at": item.refreshed_at,
        "created_at": item.created_at,
        "published_at": item.published_at,
    }


def _rate(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


# --- app ------------------------------------------------------------------


def create_app(services: Services, config: ApiConfig, lifespan=None) -> FastAPI:
    def order_json(order: Order, role: Role) -> dict[str, Any]:
        view = _order_json(order, role)
        if role is Role.ADMIN:
            view["stuck_days"] = services.orders.stuck_days(order)
        return view

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
            allow_headers=["Authorization", "Content-Type", "X-View-As"],
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
        # «Как видит клиент»: the admin may only step *down* to the client's view
        # (same rules as the client: read-only, client fields only).
        preview = role is Role.ADMIN and request.headers.get("x-view-as", "").lower() == "client"
        if preview:
            role = Role.CLIENT
        return Principal(actor=Actor.mini_app(user.id, role), role=role, user=user, preview=preview)

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
            "preview": p.preview,
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
            summary["stuck_count"] = orders.stuck_count
            summary["problem_count"] = orders.problem_count
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
        stuck: bool | None = None,
        problem: bool | None = None,
        sort: Literal["newest", "oldest", "price_desc", "price_asc", "status"] = "newest",
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        parsed = parse_status(status) if status else None
        if status and parsed is None:
            raise ValidationError(f"Неизвестный статус: {status}")
        page = services.orders.list_orders(
            p.actor,
            OrderQuery(
                status=parsed,
                search=q,
                attention=attention,
                stuck=stuck,
                problem=problem,
                sort=sort,
                offset=offset,
                limit=limit,
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
        extra = {"shop": body.shop} if "shop" in body.model_fields_set else {}
        result = services.orders.buy(
            p.actor, order_id, body.purchase_price, body.client_price, **extra
        )
        return {
            "order": order_json(result.order, p.role),
            "already_done": result.already_done,
            "change": change_json(result.change),
        }

    @app.post("/api/orders/{order_id}/rebuy")
    def rebuy(order_id: str, body: RebuyIn, p: Admin) -> dict[str, Any]:
        extra = {
            name: getattr(body, name)
            for name in ("source_url", "shop")
            if name in body.model_fields_set
        }
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
            watch_count=body.watch_count,
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
            "watch_change": change_json(result.watch_change),
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
            "watch_change": change_json(result.watch_change),
        }

    @app.post("/api/orders/{order_id}/arrival")
    def order_arrival(order_id: str, body: ArrivalIn, p: Admin) -> dict[str, Any]:
        """«Пришло на склад» with a photo uploaded by /api/images (services/arrival)."""
        if services.arrival is None or services.images is None:
            raise ConfigurationError("Загрузка фото не настроена.")
        image = services.images.read(body.photo_url)
        if image is None:
            raise NotFoundError("Фото не найдено — загрузите его заново.")
        result = services.arrival.record(
            p.actor, order_id, image, body.photo_url, body.thumbnail_url
        )
        return {
            "order": order_json(result.order, p.role),
            "status": result.status,
            "size_seen": result.size_seen,
            "review_ko": result.review_ko,
            "note": result.note,
            "moved_to_warehouse": result.moved_to_warehouse,
            "error": result.error,
        }

    # --- «Витрина» (test mode: admin only) ----------------------------------

    def _showcase():
        if services.showcase is None:
            raise ConfigurationError("Витрина не подключена.")
        return services.showcase

    @app.get("/api/showcase")
    def showcase_list(p: Any_, status: str | None = None) -> dict[str, Any]:
        liked = set(_showcase().liked(p.actor))
        items = _showcase().items(p.actor, status)
        return {"items": [showcase_json(i, liked, p.role) for i in items]}

    @app.post("/api/showcase")
    def showcase_add(body: ShowcaseAddIn, p: Admin) -> dict[str, Any]:
        return {"item": showcase_json(_showcase().add(p.actor, body.url))}

    @app.get("/api/showcase/{item_id}")
    def showcase_get(item_id: str, p: Any_) -> dict[str, Any]:
        liked = set(_showcase().liked(p.actor))
        return {"item": showcase_json(_showcase().get(p.actor, item_id), liked, p.role)}

    @app.patch("/api/showcase/{item_id}")
    def showcase_patch(item_id: str, body: ShowcasePatchIn, p: Admin) -> dict[str, Any]:
        item = _showcase().update(p.actor, item_id, body.model_dump(exclude_unset=True))
        return {"item": showcase_json(item)}

    @app.post("/api/showcase/{item_id}/refresh")
    def showcase_refresh(item_id: str, p: Any_) -> dict[str, Any]:
        if p.preview:
            raise ApiError(403, "forbidden", "В режиме «Как видит клиент» ничего не меняется.")
        liked = set(_showcase().liked(p.actor))
        item = _showcase().refresh(p.actor, item_id)
        return {"item": showcase_json(item, liked, p.role)}

    # The client's showcase writes (20.10.2026): opened a card, ♥, «Заказать».
    # Nothing here moves money; the preview «Как видит клиент» writes nothing.
    @app.post("/api/showcase/{item_id}/view")
    def showcase_viewed(item_id: str, p: Any_) -> dict[str, bool]:
        if not p.preview:
            _showcase().viewed(p.actor, item_id)
        return {"ok": True}

    @app.get("/api/showcase-stats")
    def showcase_stats(p: Admin) -> dict[str, Any]:
        client = services.clients.get(p.actor)
        names: dict[str, str] = {}
        if client is not None and client.telegram_id is not None:
            names[f"tg:{client.telegram_id}"] = client.name or "Клиент"
        if client is not None and client.second_telegram_id is not None:
            names[f"tg:{client.second_telegram_id}"] = client.second_name or "Клиент 2"
        stats = _showcase().statistics(p.actor)
        viewers = {row["viewer"] for row in stats["cards"] + stats["history"] if row.get("viewer")}
        labels = {v: names.get(v, "Вы") for v in viewers}
        return {**stats, "viewers": [{"viewer": v, "label": labels[v]} for v in sorted(viewers)]}

    @app.post("/api/showcase/{item_id}/official")
    def showcase_official(item_id: str, p: Admin) -> dict[str, Any]:
        return {"item": showcase_json(_showcase().find_official(p.actor, item_id))}

    @app.post("/api/showcase/{item_id}/status/{status}")
    def showcase_status(item_id: str, status: str, p: Admin) -> dict[str, Any]:
        return {"item": showcase_json(_showcase().set_status(p.actor, item_id, status))}

    @app.post("/api/showcase/{item_id}/delete")
    def showcase_delete(item_id: str, p: Admin) -> dict[str, bool]:
        _showcase().delete(p.actor, item_id)
        return {"ok": True}

    @app.post("/api/showcase/{item_id}/like")
    def showcase_like(item_id: str, p: Any_) -> dict[str, Any]:
        if p.preview:
            raise ApiError(403, "forbidden", "В режиме «Как видит клиент» ничего не меняется.")
        return {"liked": item_id in _showcase().toggle_like(p.actor, item_id)}

    @app.post("/api/showcase/order")
    def showcase_order(body: ShowcaseOrderIn, p: Any_) -> dict[str, Any]:
        if p.preview:
            raise ApiError(403, "forbidden", "В режиме «Как видит клиент» ничего не меняется.")
        lines = [CartLine(line.item_id, line.size, line.color) for line in body.items]
        orders = _showcase().order(p.actor, lines)
        return {"items": [order_json(o, p.role) for o in orders]}

    # «Обновить CRM» (the owner, 21.10.2026): the server's updater does the work.
    @app.get("/api/system/update")
    def update_status(p: Admin) -> dict[str, Any]:
        return services.updates.status(p.actor) if services.updates else {"installed": False}

    @app.post("/api/system/update")
    def update_request(p: Admin) -> dict[str, Any]:
        if p.preview:
            raise ApiError(403, "forbidden", "В режиме «Как видит клиент» ничего не меняется.")
        if services.updates is None:
            raise ApiError(409, "conflict", "Обновление из Mini App здесь недоступно.")
        return services.updates.request(p.actor)

    @app.get("/api/settings/shops")
    def get_shops(p: Admin) -> dict[str, Any]:
        return {"names": services.orders.shop_names(p.actor)}

    @app.put("/api/settings/shops")
    def put_shops(body: ShopsIn, p: Admin) -> dict[str, Any]:
        return {"names": services.orders.set_shop_names(p.actor, body.names)}

    @app.post("/api/orders/{order_id}/duplicate")
    def duplicate_order(order_id: str, body: DuplicateIn, p: Admin) -> dict[str, Any]:
        copies = services.orders.duplicate(p.actor, order_id, body.count)
        return {"items": [order_json(o, p.role) for o in copies]}

    @app.post("/api/shipments/{reference}/delivered")
    def shipment_delivered(reference: str, p: Any_) -> dict[str, Any]:
        """The client's only write (the owner, 16.10.2026): the parcel arrived."""
        if p.preview:
            raise ApiError(403, "forbidden", "В режиме «Как видит клиент» ничего не меняется.")
        shipment_id = services.shipments.resolve_id(reference)
        result = services.orders.mark_shipment_delivered(p.actor, shipment_id)
        return {"updated": result.updated}

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

    @app.get("/api/finance/profit-lines")
    def profit_lines(
        p: Admin,
        period: str = "all",
        date_from: Annotated[date | None, Query(alias="from")] = None,
        date_to: Annotated[date | None, Query(alias="to")] = None,
    ) -> dict[str, Any]:
        if period not in ("month", "all", "range"):
            period = "all"
        lines = services.orders.profit_lines(p.actor, period, date_from, date_to)
        return {
            "total_krw": sum(line.amount_krw for line in lines),
            "items": [
                {
                    "amount_krw": line.amount_krw,
                    "at": line.at,
                    "comment": line.comment,
                    "order": order_json(line.order, p.role) if line.order else None,
                }
                for line in lines
            ],
        }

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
        size, size_kr = order_sizes(result.size, body.text, from_caption=True)
        return {
            "recognized": result.recognized,
            "brand": result.brand,
            "model": result.model,
            "size": size,
            "size_kr": size_kr,
            "category": result.category,
            "category_code": category_from_text(result.category),
            "confidence": result.confidence,
            "not_a_product": result.not_a_product,
            "engine": result.engine,
        }

    @app.post("/api/recognize-link")
    def recognize_link(body: LinkIn, p: Admin) -> dict[str, Any]:
        if services.link_import is None:
            raise ConfigurationError("Чтение ссылок не подключено.")
        result = services.link_import.import_link(p.actor, body.url)
        return {
            "brand": result.brand,
            "model": result.model,
            "category": result.category,
            "category_code": category_from_text(result.category),
            "title": result.title,
            "photo_url": result.photo.photo_url if result.photo else None,
            "thumbnail_url": result.photo.thumbnail_url if result.photo else None,
            "engine": result.engine,
            "note": result.note,
        }

    @app.post("/api/share")
    def share_picture(
        p: Admin, file: Annotated[UploadFile, File()], picker: bool = True
    ) -> dict[str, Any]:
        """A picture made in the Mini App (shipment, balance) goes to the
        admin's Telegram to be sent on by hand; nothing is sent to the client."""
        if p.preview:
            raise PermissionDeniedError("В режиме «Как видит клиент» делиться нельзя.")
        if not config.bot_token or config.demo:
            raise ConfigurationError("Поделиться можно только в Telegram (нужен BOT_TOKEN).")
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValidationError("Картинка больше 20 МБ.")
        prepared = TelegramShare(config.bot_token).share_photo(p.user.id, data, picker=picker)
        return {"prepared_id": prepared, "in_chat": prepared is None}

    # «Скачать» a shared picture: Telegram's downloadFile needs an https link,
    # so the picture is kept in memory for a few minutes under a random token.
    # Nothing is written to disk; the token is unguessable and expires.
    share_files: dict[str, tuple[float, bytes]] = {}

    @app.post("/api/share/file")
    def share_file_put(p: Admin, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValidationError("Картинка больше 20 МБ.")
        now = time.monotonic()
        for key, (made, _) in list(share_files.items()):
            if now - made > SHARE_FILE_TTL:
                del share_files[key]
        while len(share_files) >= SHARE_FILE_MAX:
            del share_files[next(iter(share_files))]
        token = secrets.token_urlsafe(24)
        share_files[token] = (now, data)
        return {"url": f"/api/share/file/{token}.png"}

    @app.get("/api/share/file/{token}.png")
    def share_file_get(token: str) -> Response:
        item = share_files.get(token)
        if item is None or time.monotonic() - item[0] > SHARE_FILE_TTL:
            raise NotFoundError("Ссылка устарела — нажмите «Скачать» ещё раз.")
        return Response(
            item[1],
            media_type="image/png",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="crm.png"',
            },
        )

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
    # Shipping lines show the parcel: its tracking code and a photo.
    shipments: dict[str, dict[str, Any]] = {}
    for shipment_id in {e.shipment_id for e in entries if e.shipment_id}:
        try:
            found, _ = services.shipments.get_shipment(p.actor, shipment_id)
        except NotFoundError:
            continue
        shipments[shipment_id] = {
            "id": found.id,
            "number": found.shipment_number,
            "tracking_code": found.tracking_code,
            "thumbnail_url": found.thumbnail_url or found.photo_url,
        }
    items = ledger_rows(entries, p.role)  # a re-purchase is merged into its charge line
    for view in items:
        order = orders.get(view["order_id"]) if view["order_id"] else None
        view["order"] = (
            {"id": order.id, "title": order.title, "thumbnail_url": order.thumbnail_url}
            if order
            else None
        )
        view["shipment"] = shipments.get(view["shipment_id"]) if view["shipment_id"] else None
    return items

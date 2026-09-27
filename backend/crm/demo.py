"""Demo data for `python -m crm.bot --demo` and `python -m crm.server --demo`.

Everything lives in memory: Firebase is not touched and every restart starts
over. The history is produced by the real services (deposit, /buy, statuses,
shipments with shipping charges, a cancellation), so the demo also exercises
the actual business rules. Dates are spread over the last three weeks.
"""

import io
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from PIL import Image, ImageDraw, ImageFont

from crm.domain.enums import OrderStatus
from crm.services.common import Actor
from crm.services.container import build_services
from crm.services.order_service import OrderUpdate
from crm.services.shipment_service import ShipmentDetails
from crm.storage.blobs import BlobStorage
from crm.storage.memory import InMemoryDatabase

logger = logging.getLogger(__name__)

DEMO_BALANCE = 0
DEMO_DEPOSIT = 8_000_000

# id, brand, model, size, purchase, client price, tint
_ORDERS = [
    ("n117", "Maison Kitsuné", "Fox Head Tee", "M", 62_000, 79_000, (214, 204, 190)),
    ("n118", "New Balance", "990v6", "275", 210_000, 245_000, (196, 198, 196)),
    ("n119", "Adidas", "Samba OG", "255", 118_000, 139_000, (206, 200, 186)),
    ("n120", "Stone Island", "Soft Shell-R", "L", 480_000, 540_000, (180, 188, 176)),
    ("n121", "Arc'teryx", "Beta LT", "M", 520_000, 590_000, (168, 180, 190)),
    ("n122", "Nike", "Air Max 95", "270", 189_000, 219_000, (200, 196, 204)),
    ("n123", "Salomon", "XT-6", "265", 205_000, 239_000, (190, 196, 184)),
    ("n124", "Asics", "Gel-Kayano 14", "270", None, None, (204, 194, 184)),
    ("n125", "Nike", "Dunk Low Panda", "260", None, None, (188, 188, 192)),
]


class _DemoClock:
    """Starts three weeks ago; `advance` moves time between demo steps."""

    def __init__(self) -> None:
        self.current = datetime.now(timezone.utc) - timedelta(days=21)

    def now(self) -> datetime:
        self.current += timedelta(minutes=3)
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


def _placeholder(brand: str, model: str, tint: tuple[int, int, int]) -> bytes:
    """A calm product placeholder: soft gradient with the brand and model."""
    size = 1200
    image = Image.new("RGB", (size, size), tint)
    draw = ImageDraw.Draw(image)
    top = tuple(min(255, c + 30) for c in tint)
    for y in range(size):
        t = y / size
        draw.line(
            [(0, y), (size, y)],
            fill=tuple(int(a + (b - a) * t) for a, b in zip(top, tint, strict=True)),
        )
    ink = tuple(max(0, c - 120) for c in tint)
    draw.rounded_rectangle((210, 330, 990, 870), radius=60, outline=ink, width=6)
    brand_font = ImageFont.load_default(size=96)
    model_font = ImageFont.load_default(size=54)
    for text, font, y in ((brand.upper(), brand_font, 520), (model, model_font, 650)):
        width = draw.textlength(text, font=font)
        draw.text(((size - width) / 2, y), text, fill=ink, font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def create_demo_database(
    client_telegram_id: int | None, blob_storage: BlobStorage | None = None
) -> InMemoryDatabase:
    db = InMemoryDatabase()
    clock = _DemoClock()
    db.seed(
        "client_info",
        "main_client",
        {"telegram_id": client_telegram_id, "name": "Демо-клиент", "balance": DEMO_BALANCE},
    )
    services = build_services(db, frozenset(), clock, blob_storage=blob_storage)
    admin = Actor.system()
    services.finance.set_rate(admin, Decimal(1350))

    for order_id, brand, model, size, _, _, tint in _ORDERS:
        photo = {}
        if services.images is not None:
            stored = services.images.store(admin, _placeholder(brand, model, tint), folder="demo")
            photo = {"photo_url": stored.photo_url, "thumbnail_url": stored.thumbnail_url}
        db.seed(
            "orders",
            order_id,
            {
                "order_id": order_id,
                "status": OrderStatus.NEW.value,
                "brand": brand,
                "model": model,
                "size": size,
                "purchase_price": None,
                "client_price": None,
                "profit": None,
                "charged_amount_krw": 0,
                "cargo_code": None,
                "shipment_id": None,
                "attention_required": False,
                "created_at": clock.now(),
                **photo,
            },
        )

    clock.advance(days=1)
    services.finance.deposit(admin, DEMO_DEPOSIT, "Перевод от клиента")
    for order_id, _brand, _model, _size, purchase, price, _tint in _ORDERS:
        if purchase is not None and price is not None:
            clock.advance(hours=7)
            services.orders.buy(admin, order_id, purchase, price)

    clock.advance(days=2)
    services.orders.cancel(admin, "n117")
    services.orders.set_status(admin, ["n118", "n119", "n120", "n121"], OrderStatus.WAREHOUSE)

    clock.advance(days=3)
    first = services.shipments.ship_orders(
        admin,
        ["n118", "n119"],
        "KR100200300",
        ShipmentDetails(box_number="B-1", weight_kg=4.2, shipping_cost_krw=48_000),
    )
    clock.advance(days=6)
    services.orders.set_status(admin, ["n118", "n119"], OrderStatus.DELIVERED)
    assert first.shipment is not None

    clock.advance(days=2)
    services.orders.set_status(admin, ["n122", "n123"], OrderStatus.WAREHOUSE)
    services.shipments.ship_orders(
        admin,
        ["n120", "n121"],
        "KR100200417",
        ShipmentDetails(
            box_number="B-2",
            weight_kg=6.8,
            shipping_cost_krw=71_000,
            comment="Две куртки, коробка усилена",
        ),
    )
    clock.advance(days=1)
    services.orders.update_details(
        admin,
        "n125",
        OrderUpdate(
            attention_required=True,
            client_comment="Размер 260 закончился, есть 265 — подойдёт?",
            internal_comment="Продавец обещал ответ до пятницы",
        ),
    )
    services.orders.update_details(admin, "n124", OrderUpdate(client_comment="Ищем по лучшей цене"))
    logger.info("Demo data ready: %s orders", len(_ORDERS))
    return db

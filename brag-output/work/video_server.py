"""Demo server with the data used in the launch video (real services, own data set)."""
import sys, logging
from decimal import Decimal
from pathlib import Path
import crm.demo as demo
from crm.domain.enums import OrderStatus
from crm.services.common import Actor
from crm.services.container import build_services
from crm.services.order_service import OrderUpdate
from crm.services.shipment_service import ShipmentDetails
from crm.storage.memory import InMemoryDatabase

A = Path(__file__).parent / "assets"
# id, brand, model, size, purchase, client price, photo file
ORDERS = [   # the ten orders the video shows (newest; ids N46..N55 after 45 older ones)
    ("N46", "On", "Cloud 5 Waterproof", "270", 165_000, 189_000, "1.jpg"),
    ("N47", "adidas", "Sportswear Denim Track Top", "L", 98_000, 119_000, "2.jpg"),
    ("N48", "Nike", "Air Max Flyknit Bloom", "255", 176_000, 205_000, "3c.jpg"),
    ("N49", "Timex", "Expedition Scout", "-", 72_000, 89_000, "4.jpg"),
    ("N50", "Represent", "Denim Track Jacket & Pants", "M", 410_000, 469_000, "5.jpg"),
    ("N51", "Nike", "Tech Fleece Windrunner", "L", 235_000, 269_000, "6.jpg"),
    ("N52", "Nike", "Air Max 90", "270", 128_000, 155_000, "7c.jpg"),
    ("N53", "adidas", "Adistar Cushion", "275", 142_000, 169_000, "8.jpg"),
    ("N54", "Swatch", "Skin", "-", 88_000, 109_000, "9c.jpg"),
    ("N55", "Swatch", "Irony", "-", 142_000, 169_000, "10c.jpg"),
]
BOUGHT = ["N46", "N47", "N48", "N49", "N50", "N51", "N52", "N53", "N55"]   # N54 stays "new"
# older, already delivered orders (history): (count, start date UTC, first id) → profit in the millions
HISTORY = [(30, (2026, 9, 8)), (15, (2026, 10, 1))]
SIZES = {"On": ["265", "270", "275"], "Nike": ["255", "265", "270", "280"], "adidas": ["260", "270", "275", "L"], "Represent": ["M", "L"], "Swatch": [None], "Timex": [None]}


def create(client_telegram_id, blob_storage=None):
    from datetime import datetime, timedelta, timezone
    db = InMemoryDatabase(); clock = demo._DemoClock()
    db.seed("client_info", "main_client", {"telegram_id": client_telegram_id, "name": "Клиент", "balance": 0})
    s = build_services(db, frozenset(), clock, blob_storage=blob_storage)
    admin = Actor.system()
    s.finance.set_rate(admin, Decimal(1350))
    photos = {}
    for oid, brand, model, size, p, c, photo in ORDERS:
        stored = s.images.store(admin, (A / photo).read_bytes(), folder="demo")
        photos[oid] = (stored.photo_url, stored.thumbnail_url)

    def seed(oid, brand, model, size, purl, turl):
        db.seed("orders", oid, {"order_id": oid, "status": OrderStatus.NEW.value, "brand": brand, "model": model,
            "size": size, "purchase_price": None, "client_price": None, "profit": None,
            "charged_amount_krw": 0, "cargo_code": None, "shipment_id": None, "attention_required": False,
            "created_at": clock.now(), "photo_url": purl, "thumbnail_url": turl})

    # --- history: delivered orders (they sit below the ten new ones in every list) ---
    import random
    rnd = random.Random(5); n = 0; track = 100200100
    for count, (y, m, d) in HISTORY:
        clock.current = datetime(y, m, d, 1, 0, tzinfo=timezone.utc)
        ids = []
        for _ in range(count):
            n += 1; oid = f"N{n}"; base = ORDERS[rnd.randrange(len(ORDERS))]
            purchase = int(base[4] * rnd.uniform(1.0, 1.6) // 1000 * 1000)
            margin = rnd.randrange(45, 95) * 1000
            seed(oid, base[1], base[2], rnd.choice(SIZES[base[1]]), *photos[base[0]])
            ids.append((oid, purchase, purchase + margin)); clock.advance(hours=3)
        total = sum(c for _, _, c in ids)
        s.finance.deposit(admin, (total // 1_000_000 + 2) * 1_000_000, "Пополнение")
        for oid, pp, cp in ids:
            clock.advance(minutes=20); s.orders.buy(admin, oid, pp, cp)
        for k in range(0, len(ids), 5):
            batch = [oid for oid, _, _ in ids[k:k + 5]]
            clock.advance(hours=10); s.orders.set_status(admin, batch, OrderStatus.WAREHOUSE)
            track += 7
            s.shipments.ship_orders(admin, batch, f"KR{track}", ShipmentDetails(box_number=f"A-{track % 100}", weight_kg=round(rnd.uniform(3, 9), 1), shipping_cost_krw=rnd.randrange(40, 90) * 1000))
            clock.advance(hours=6); s.orders.set_status(admin, batch, OrderStatus.DELIVERED)

    # --- the ten orders the video shows: 2 Oct → 5 Oct ---
    clock.current = datetime(2026, 10, 2, 6, 0, tzinfo=timezone.utc)
    price = {}
    for oid, brand, model, size, p, c, photo in ORDERS:
        price[oid] = (p, c); seed(oid, brand, model, None if size == "-" else size, *photos[oid])
    # shop link and private note: visible only to the admin (scene 6)
    s.orders.update_details(admin, "N51", OrderUpdate(source_url="https://store.example.kr/nike-tech-fleece-windrunner",
        internal_comment="Скидка продавца 5% при следующем заказе"))
    clock.advance(hours=6)
    s.finance.deposit(admin, 2_500_000, "Пополнение")
    for oid in BOUGHT[:5]:
        clock.advance(hours=2); s.orders.buy(admin, oid, *price[oid])
    clock.advance(hours=10)
    s.finance.deposit(admin, 1_500_000, "Пополнение")
    for oid in BOUGHT[5:]:
        clock.advance(hours=2); s.orders.buy(admin, oid, *price[oid])
    clock.advance(hours=8)
    s.orders.set_status(admin, ["N46", "N47", "N48", "N49", "N52", "N53", "N55"], OrderStatus.WAREHOUSE)
    clock.advance(hours=6)
    shelf = s.images.store(admin, (A / "11.jpg").read_bytes(), folder="demo")
    s.shipments.ship_orders(admin, ["N52", "N53"], "KR100200300", ShipmentDetails(box_number="A-1", weight_kg=3.9,
        shipping_cost_krw=52_000, photos=[{"photo_url": shelf.photo_url, "thumbnail_url": shelf.thumbnail_url}]))
    clock.advance(hours=20)
    s.orders.set_status(admin, ["N52", "N53"], OrderStatus.DELIVERED)
    clock.advance(hours=4)
    inside = s.images.store(admin, (A / "13.jpg").read_bytes(), folder="demo")
    label = s.images.store(admin, (A / "12.jpg").read_bytes(), folder="demo")
    s.shipments.ship_orders(admin, ["N46", "N47", "N55"], "KR100200417", ShipmentDetails(box_number="AV-1506", weight_kg=5.2,
        shipping_cost_krw=58_000, comment="Три позиции, коробка целая",
        photos=[{"photo_url": p.photo_url, "thumbnail_url": p.thumbnail_url} for p in (inside, label)]))
    return db


class _DemoRecognizer:
    """No Gemini key in the video environment: a prepared answer for the AI icon (scene 7)."""

    def recognize(self, image, text):
        from crm.services.recognition import Recognition
        return Recognition(brand="On", model="Cloud 5 Waterproof", category="кроссовки", size="270",
                           confidence=0.93, engine="gemini (демо)")


import crm.services.recognition as _rec
_rec.create_recognizer = lambda *a, **k: _DemoRecognizer()

demo.create_demo_database = create
import crm.server
sys.argv = ["crm.server", "--demo"]
crm.server.main()

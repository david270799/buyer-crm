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
ORDERS = [
    ("N1", "On", "Cloud 5 Waterproof", "270", 165_000, 189_000, "1.jpg"),
    ("N2", "adidas", "Sportswear Denim Track Top", "L", 98_000, 119_000, "2.jpg"),
    ("N3", "Nike", "Air Max Flyknit Bloom", "255", 176_000, 205_000, "3c.jpg"),
    ("N4", "Timex", "Expedition Scout", "-", 72_000, 89_000, "4.jpg"),
    ("N5", "Represent", "Denim Track Jacket & Pants", "M", 410_000, 469_000, "5.jpg"),
    ("N6", "Nike", "Tech Fleece Windrunner", "L", 235_000, 269_000, "6.jpg"),
    ("N7", "Nike", "Air Max 90", "270", 128_000, 155_000, "7c.jpg"),
    ("N8", "adidas", "Adistar Cushion", "275", 142_000, 169_000, "8.jpg"),
    ("N9", "Swatch", "Skin", "-", 88_000, 109_000, "9c.jpg"),
    ("N10", "Swatch", "Irony", "-", 142_000, 169_000, "10c.jpg"),
]
BOUGHT = ["N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8"]   # N9, N10 stay "new"

def create(client_telegram_id, blob_storage=None):
    db = InMemoryDatabase(); clock = demo._DemoClock()
    db.seed("client_info", "main_client", {"telegram_id": client_telegram_id, "name": "Клиент", "balance": 0})
    s = build_services(db, frozenset(), clock, blob_storage=blob_storage)
    admin = Actor.system()
    s.finance.set_rate(admin, Decimal(1350))
    price = {}
    for oid, brand, model, size, p, c, photo in ORDERS:
        stored = s.images.store(admin, (A / photo).read_bytes(), folder="demo")
        price[oid] = (p, c)
        db.seed("orders", oid, {"order_id": oid, "status": OrderStatus.NEW.value, "brand": brand, "model": model,
            "size": None if size == "-" else size, "purchase_price": None, "client_price": None, "profit": None,
            "charged_amount_krw": 0, "cargo_code": None, "shipment_id": None, "attention_required": False,
            "created_at": clock.now(), "photo_url": stored.photo_url, "thumbnail_url": stored.thumbnail_url})
    # shop link and private note: visible only to the admin (scene 6)
    s.orders.update_details(admin, "N6", OrderUpdate(source_url="https://store.example.kr/nike-tech-fleece-windrunner",
        internal_comment="Скидка продавца 5% при следующем заказе"))
    clock.advance(days=1)
    s.finance.deposit(admin, 2_500_000, "Пополнение")
    for oid in BOUGHT[:4]:
        clock.advance(hours=6); s.orders.buy(admin, oid, *price[oid])
    clock.advance(days=2)
    s.finance.deposit(admin, 1_500_000, "Пополнение")
    for oid in BOUGHT[4:]:
        clock.advance(hours=5); s.orders.buy(admin, oid, *price[oid])
    clock.advance(days=2)
    s.orders.set_status(admin, ["N1", "N2", "N3", "N4", "N7", "N8"], OrderStatus.WAREHOUSE)
    clock.advance(days=1)
    s.shipments.ship_orders(admin, ["N1", "N2"], "KR100200300", ShipmentDetails(box_number="A-1", weight_kg=3.9, shipping_cost_krw=52_000))
    clock.advance(days=5)
    s.orders.set_status(admin, ["N1", "N2"], OrderStatus.DELIVERED)
    clock.advance(days=1)
    box = s.images.store(admin, (A / "11.jpg").read_bytes(), folder="demo")
    s.shipments.ship_orders(admin, ["N7", "N8"], "KR100200417", ShipmentDetails(box_number="A-2", weight_kg=4.6,
        shipping_cost_krw=47_000, comment="Две пары, коробки целые", photo_url=box.photo_url, thumbnail_url=box.thumbnail_url))
    return db

demo.create_demo_database = create
import crm.server
sys.argv = ["crm.server", "--demo"]
crm.server.main()

"""Demo server with the data used in the launch video (real services, own data set)."""
import sys, logging
from decimal import Decimal
from pathlib import Path
import crm.demo as demo
from crm.domain.enums import OrderStatus
from crm.services.common import Actor
from crm.services.container import build_services
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
]

def create(client_telegram_id, blob_storage=None):
    db = InMemoryDatabase(); clock = demo._DemoClock()
    db.seed("client_info", "main_client", {"telegram_id": client_telegram_id, "name": "Клиент", "balance": 0})
    s = build_services(db, frozenset(), clock, blob_storage=blob_storage)
    admin = Actor.system()
    s.finance.set_rate(admin, Decimal(1350))
    for oid, brand, model, size, _p, _c, photo in ORDERS:
        stored = s.images.store(admin, (A / photo).read_bytes(), folder="demo")
        db.seed("orders", oid, {"order_id": oid, "status": OrderStatus.NEW.value, "brand": brand, "model": model,
            "size": None if size == "-" else size, "purchase_price": None, "client_price": None, "profit": None,
            "charged_amount_krw": 0, "cargo_code": None, "shipment_id": None, "attention_required": False,
            "created_at": clock.now(), "photo_url": stored.photo_url, "thumbnail_url": stored.thumbnail_url})
    clock.advance(days=1)
    s.finance.deposit(admin, 2_500_000, "Пополнение")
    for oid, _b, _m, _s, p, c, _ph in ORDERS[:2]:
        clock.advance(hours=6); s.orders.buy(admin, oid, p, c)
    clock.advance(days=2)
    s.finance.deposit(admin, 1_500_000, "Пополнение")
    for oid, _b, _m, _s, p, c, _ph in ORDERS[2:]:
        clock.advance(hours=5); s.orders.buy(admin, oid, p, c)
    clock.advance(days=2)
    s.orders.set_status(admin, ["N1", "N2", "N3", "N4"], OrderStatus.WAREHOUSE)
    clock.advance(days=2)
    s.shipments.ship_orders(admin, ["N1", "N2"], "KR100200300", ShipmentDetails(box_number="A-1", weight_kg=3.9, shipping_cost_krw=52_000))
    clock.advance(days=5)
    s.orders.set_status(admin, ["N1", "N2"], OrderStatus.DELIVERED)
    clock.advance(days=1)
    s.shipments.ship_orders(admin, ["N3"], "KR100200417", ShipmentDetails(box_number="A-2", weight_kg=1.4, shipping_cost_krw=41_000))
    return db

demo.create_demo_database = create
import crm.server
sys.argv = ["crm.server", "--demo"]
crm.server.main()

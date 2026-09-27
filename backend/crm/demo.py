"""Demo data for `python -m crm.bot --demo`.

The bot then runs on an in-memory database: Firebase is not touched, nothing
is saved, and every restart starts from this data again. Safe for trying
/buy, /cancel and /cargo without moving the real client balance.
"""

from datetime import datetime, timedelta, timezone

from crm.storage.memory import InMemoryDatabase

DEMO_BALANCE = 5_000_000


def create_demo_database(client_telegram_id: int | None) -> InMemoryDatabase:
    db = InMemoryDatabase()
    created = datetime.now(timezone.utc) - timedelta(days=3)
    db.seed(
        "client_info",
        "main_client",
        {"telegram_id": client_telegram_id, "name": "Демо-клиент", "balance": DEMO_BALANCE},
    )
    db.seed("settings", "general", {"krw_per_usd": 1350})

    orders = [
        ("n121", "new", "Nike", "Air Max 95", "270", None, None),
        ("n122", "new", "Adidas", "Samba OG", "255", None, None),
        ("n123", "bought", "New Balance", "990v6", "275", 210_000, 245_000),
        ("n124", "warehouse", "Stone Island", "Soft Shell-R", "L", 480_000, 540_000),
        ("n125", "warehouse", "Arc'teryx", "Beta LT", "M", 520_000, 590_000),
    ]
    for order_id, status, brand, model, size, purchase, client_price in orders:
        charged = client_price if status != "new" else 0
        db.seed(
            "orders",
            order_id,
            {
                "order_id": order_id,
                "status": status,
                "brand": brand,
                "model": model,
                "size": size,
                "purchase_price": purchase,
                "client_price": client_price,
                "profit": client_price - purchase if client_price and purchase else None,
                "charged_amount_krw": charged,
                "cargo_code": None,
                "shipment_id": None,
                "created_at": created,
                "updated_at": created,
            },
        )
    return db

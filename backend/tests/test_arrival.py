import pytest
from conftest import START_BALANCE, balance, seed_order

from crm.domain.errors import ConflictError, PermissionDeniedError
from crm.services.arrival import MATCH, MISMATCH, SKIPPED, UNCLEAR, ArrivalService
from crm.services.order_service import OrderUpdate
from crm.services.recognition import RecognitionError

pytestmark = pytest.mark.usefixtures("client_doc")


class FakeChecker:
    def __init__(self, answer=None, error=None):
        self.answer = answer or {}
        self.error = error
        self.calls = []

    def check_arrival(self, image, item, size):
        self.calls.append((item, size))
        if self.error:
            raise RecognitionError(self.error)
        return {"confidence": 0.9, "note": None, "review_ko": "디자인이 예뻐요", **self.answer}


def make(db, services, clock, checker):
    from crm.repositories import OrderRepository

    return ArrivalService(
        db, clock, OrderRepository(), services.orders, services.orders._auditor, checker
    )


def bought(db, services, admin, size="270", **extra):
    seed_order(db, "N5", size=size, **extra)
    services.orders.buy(admin, "5", 100_000, 150_000, shop="Musinsa")


def test_same_size_moves_to_warehouse_and_saves_review(db, services, admin, clock):
    bought(db, services, admin)
    checker = FakeChecker({"size_seen": "270", "matches": True})
    result = make(db, services, clock, checker).record(
        admin, "N5", b"img", "/media/a.webp", "/media/a_t.webp"
    )

    assert result.status == MATCH and result.moved_to_warehouse
    order = db.get("orders", "N5")
    assert order["status"] == "warehouse"
    assert order["arrival_photo_url"] == "/media/a.webp"
    assert order["arrival_check"]["status"] == MATCH
    assert order["review_ko"] == "디자인이 예뻐요"
    assert balance(db) == START_BALANCE - 150_000  # no money moved by the arrival


def test_other_size_is_a_mismatch(db, services, admin, clock):
    bought(db, services, admin)
    checker = FakeChecker({"size_seen": "265", "matches": False})
    result = make(db, services, clock, checker).record(admin, "5", b"img", None, None)
    assert result.status == MISMATCH and result.size_seen == "265"


def test_unsure_answer_is_unclear(db, services, admin, clock):
    bought(db, services, admin)
    checker = FakeChecker({"size_seen": "265", "matches": False, "confidence": 0.3})
    assert make(db, services, clock, checker).record(admin, "5", b"i", None, None).status == UNCLEAR


def test_watches_are_not_size_checked_but_get_a_review(db, services, admin, clock):
    bought(db, services, admin, size=None)
    services.orders.update_details(admin, "5", OrderUpdate(category="watch"))
    checker = FakeChecker({"size_seen": None})
    result = make(db, services, clock, checker).record(admin, "5", b"i", None, None)
    assert result.status == SKIPPED and result.review_ko


def test_gemini_failure_still_records_the_arrival(db, services, admin, clock):
    bought(db, services, admin)
    result = make(db, services, clock, FakeChecker(error="сеть")).record(
        admin, "5", b"i", None, None
    )
    assert result.status == SKIPPED and result.error == "сеть" and result.moved_to_warehouse


def test_rules(db, services, admin, client_actor, clock):
    seed_order(db, "N5")  # «Новый»
    service = make(db, services, clock, FakeChecker())
    with pytest.raises(ConflictError):
        service.record(admin, "5", b"i", None, None)
    with pytest.raises(PermissionDeniedError):
        service.record(client_actor, "5", b"i", None, None)


def test_waiting_lists_bought_orders(db, services, admin, clock):
    bought(db, services, admin)
    seed_order(db, "N6")
    assert [o.id for o in make(db, services, clock, None).waiting(admin)] == ["N5"]

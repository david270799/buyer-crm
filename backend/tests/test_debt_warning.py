import pytest
from conftest import CLIENT_TG, START_BALANCE

from crm.services.ledger import debt_level

pytestmark = pytest.mark.usefixtures("client_doc")


def warnings(db) -> list[dict]:
    return sorted(
        (data for _, data in db.query("events") if data["type"] == "debt_warning"),
        key=lambda d: d["created_at"],
    )


def test_debt_level():
    assert debt_level(500_000) == 0
    assert debt_level(-999_999) == 0
    assert debt_level(-1_000_000) == 1
    assert debt_level(-2_150_000) == 2


def test_each_million_warns_once_and_a_big_jump_warns_once(db, services, admin):
    services.finance.adjust(admin, -(START_BALANCE + 900_000), "x")  # → −900,000: no warning
    assert warnings(db) == []

    services.finance.adjust(admin, -200_000, "x")  # → −1,100,000: passed 1M
    services.finance.adjust(admin, -100_000, "x")  # → −1,200,000: same million
    services.finance.adjust(admin, -2_000_000, "x")  # → −3,200,000: passed 2M and 3M → one
    found = warnings(db)
    assert len(found) == 2
    assert "1,000,000" in found[0]["title"] and "dan oshdi" in found[0]["title"]
    assert "3,000,000" in found[1]["title"]
    assert "3,200,000" in found[1]["body"]

    services.finance.deposit(admin, 3_000_000, "x")  # paying back: no warning
    services.finance.adjust(admin, -1_000_000, "x")  # −1,200,000 again: passed 1M again
    assert len(warnings(db)) == 3


def test_warning_goes_to_the_client_even_with_notifications_off(db, services, admin):
    services.finance.adjust(admin, -(START_BALANCE + 1_500_000), "x")
    batch = services.notifications.due()
    debt = [d for d in batch.deliveries if d.event.type == "debt_warning"]
    assert [d.chat_ids for d in debt] == [(CLIENT_TG,)]

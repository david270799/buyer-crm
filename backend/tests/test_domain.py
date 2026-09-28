from datetime import datetime, timezone
from decimal import Decimal

import pytest

from crm.domain.enums import OrderStatus, Role, parse_status
from crm.domain.errors import ValidationError
from crm.domain.ids import (
    make_shipment_id,
    normalize_order_id,
    normalize_tracking_code,
    order_number,
    parse_order_ids,
)
from crm.domain.models import ClientInfo, GeneralSettings, Order
from crm.domain.money import format_krw, format_usd, krw_to_usd, parse_krw, parse_rate
from crm.domain.timeutil import format_datetime, to_local
from crm.domain.views import ADMIN_ONLY_ORDER_FIELDS, order_view


@pytest.mark.parametrize(
    "token, expected",
    [
        ("5", "N5"),
        ("N5", "N5"),
        ("N5", "N5"),
        ("N05", "N5"),
        ("#125", "N125"),
        (" 7 ", "N7"),
    ],
)
def test_normalize_order_id(token, expected):
    assert normalize_order_id(token) == expected


@pytest.mark.parametrize("token", ["0", "N0", "x5", "5a", "", "n-1", "12345678"])
def test_normalize_order_id_rejects(token):
    with pytest.raises(ValidationError):
        normalize_order_id(token)


def test_parse_order_ids_dedupes_and_reports_invalid():
    assert parse_order_ids(["5", "N5", "7", "abc", "N7"]) == (["N5", "N7"], ["abc"])


def test_order_number():
    assert order_number("N125") == 125
    assert order_number("SHP-1") is None
    assert order_number("N05") is None  # not a canonical document ID


def test_tracking_code():
    assert normalize_tracking_code(" trk-12ab ") == "TRK-12AB"
    assert make_shipment_id(2026, 7) == "SHP-2026-007"
    assert make_shipment_id(2026, 1234) == "SHP-2026-1234"


@pytest.mark.parametrize(
    "token, expected",
    [
        ("170000", 170_000),
        ("170,000", 170_000),
        ("1_000_000", 1_000_000),
        ("₩5000", 5_000),
        ("+5000", 5_000),
    ],
)
def test_parse_krw(token, expected):
    assert parse_krw(token) == expected


@pytest.mark.parametrize("token", ["1.5", "12,34", "abc", "", "-5", "1000000001", "1,0000"])
def test_parse_krw_rejects(token):
    with pytest.raises(ValidationError):
        parse_krw(token)


def test_parse_krw_negative_when_allowed():
    assert parse_krw("-15,000", allow_negative=True) == -15_000


def test_format_money():
    assert format_krw(12_500_000) == "₩ 12,500,000"
    assert format_krw(-2_400_000) == "- ₩ 2,400,000"
    assert format_krw(5_000, signed=True) == "+ ₩ 5,000"
    assert format_krw(0, signed=True) == "₩ 0"
    assert format_usd(krw_to_usd(-2_400_000, Decimal(1350))) == "- $ 1,778"
    assert format_usd(Decimal("0.5")) == "$ 1"


def test_parse_rate():
    assert parse_rate("1350") == Decimal("1350")
    assert parse_rate("1352,5") == Decimal("1352.5")
    for bad in ("abc", "50", "20000"):
        with pytest.raises(ValidationError):
            parse_rate(bad)


def test_parse_status_aliases():
    assert parse_status("Склад") is OrderStatus.WAREHOUSE
    assert parse_status(" CARGO ") is OrderStatus.CARGO
    assert parse_status("canceled") is OrderStatus.CANCELLED
    assert parse_status("в пути") is None
    assert parse_status(3) is None


def test_lenient_order_parsing():
    order = Order.from_doc(
        "N3",
        {
            "order_id": 3,
            "status": "bought",
            "purchase_price": 100000.0,
            "client_price": "120,000",
            "cargo_code": "",
        },
    )
    assert order.status is OrderStatus.BOUGHT
    assert order.purchase_price == 100_000
    assert order.client_price == 120_000
    assert order.profit == 20_000
    assert order.cargo_code is None


@pytest.mark.parametrize("status", ["new", "bought", "delivered", "что-то"])
def test_missing_charge_means_nothing_was_charged(status):
    order = Order.from_doc("N1", {"status": status, "client_price": 5})
    assert order.charged_amount_krw == 0 and not order.is_charged


def test_recorded_charge_is_read():
    order = Order.from_doc(
        "N1", {"status": "warehouse", "client_price": 5, "charged_amount_krw": 5}
    )
    assert order.charged_amount_krw == 5 and order.is_charged


def test_client_info_parsing():
    info = ClientInfo.from_doc("main_client", {"telegram_id": "2002", "balance": -50.0})
    assert info.telegram_id == 2002 and info.balance == -50
    assert ClientInfo.from_doc("main_client", {"balance": None}).balance is None


def test_settings_parsing():
    assert GeneralSettings.from_doc({"krw_per_usd": 1350}).krw_per_usd == Decimal(1350)
    assert GeneralSettings.from_doc({"krw_per_usd": -1}).krw_per_usd is None
    assert GeneralSettings.from_doc(None).krw_per_usd is None


def test_client_view_hides_internal_fields():
    order = Order.from_doc(
        "N5",
        {
            "status": "bought",
            "purchase_price": 140_000,
            "client_price": 170_000,
            "internal_comment": "секрет",
            "client_comment": "ok",
            "created_by": "tg:1",
            "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "bought_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        },
    )
    client = order_view(order, Role.CLIENT)
    admin = order_view(order, Role.ADMIN)
    for name in ADMIN_ONLY_ORDER_FIELDS:
        assert name not in client
        assert name in admin
    assert "updated_at" not in client["timestamps"]
    assert "bought_at" in client["timestamps"]
    assert client["client_price"] == 170_000


def test_seoul_time():
    moment = datetime(2026, 9, 26, 20, 30, tzinfo=timezone.utc)
    assert to_local(moment).day == 27
    assert format_datetime(moment) == "27 сен 2026, 05:30"

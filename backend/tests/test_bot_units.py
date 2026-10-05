from decimal import Decimal

import pytest

from crm.bot import formatting as fmt
from crm.bot import parsing
from crm.bot.handlers.errors import CONTENTION_TEXT, INTERNAL_ERROR_TEXT, user_text
from crm.bot.handlers.reply import chunks
from crm.config import load_settings
from crm.domain.enums import OrderStatus, Role
from crm.domain.errors import ConfigurationError, NotFoundError, ValidationError
from crm.repositories import ClientRepository
from crm.services.auth import RoleResolver
from crm.services.finance_service import BalanceView
from crm.storage import TransactionContentionError
from crm.storage.memory import InMemoryDatabase

# --- parsing ---------------------------------------------------------------


def test_parse_buy():
    assert parsing.parse_buy("5 140,000 170000") == ("N5", 140_000, 170_000)
    for bad in (None, "5 140000", "5 1 2 3", "x 1 2"):
        with pytest.raises(ValidationError):
            parsing.parse_buy(bad)


def test_parse_status_in_any_position():
    assert parsing.parse_status_command("warehouse 5 7") == (OrderStatus.WAREHOUSE, ["N5", "N7"])
    assert parsing.parse_status_command("5,7 склад") == (OrderStatus.WAREHOUSE, ["N5", "N7"])
    for bad in ("5 7", "warehouse", "warehouse cargo 5", "warehouse 5 x"):
        with pytest.raises(ValidationError):
            parsing.parse_status_command(bad)


def test_parse_cargo():
    assert parsing.parse_cargo("TRACK 5 N10, 18") == ("TRACK", ["N5", "N10", "N18"])
    with pytest.raises(ValidationError, match="Некорректные номера"):
        parsing.parse_cargo("TRACK 5 abc")
    with pytest.raises(ValidationError):
        parsing.parse_cargo("TRACK")


def test_parse_amount_with_comment():
    assert parsing.parse_amount_with_comment(
        "5,000,000 перевод 26.09", "u", allow_negative=False
    ) == (5_000_000, "перевод 26.09")
    assert parsing.parse_amount_with_comment("-15000", "u", allow_negative=True) == (-15_000, None)
    with pytest.raises(ValidationError):
        parsing.parse_amount_with_comment("", "u", allow_negative=False)


def test_parse_rate_command():
    assert parsing.parse_rate_command(None) is None
    assert parsing.parse_rate_command("1352,5") == Decimal("1352.5")


# --- formatting ------------------------------------------------------------


def test_stepper():
    assert fmt.stepper(OrderStatus.WAREHOUSE) == "● ● ● ○ ○"
    assert fmt.stepper(OrderStatus.DELIVERED) == "● ● ● ● ●"
    assert fmt.stepper(OrderStatus.CANCELLED) == "✖️ Отменён"
    assert fmt.stepper(None) == "○ ○ ○ ○ ○"


def test_balance_text():
    assert "(долг)" in fmt.balance(BalanceView(-2_400_000, Decimal(1350)))
    assert "- $ 1,778" in fmt.balance(BalanceView(-2_400_000, Decimal(1350)))
    assert "не задан" in fmt.balance(BalanceView(100, None))


def test_error_texts_never_leak_internals():
    assert user_text(NotFoundError("Заказ N1 не найден.")) == "❌ Заказ N1 не найден."
    assert user_text(TransactionContentionError("x")) == CONTENTION_TEXT
    assert user_text(RuntimeError("google.api_core secret path")) == INTERNAL_ERROR_TEXT


def test_chunks_split_long_text_on_lines():
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(200))
    parts = chunks(text, limit=1000)
    assert all(len(part) <= 1000 for part in parts)
    assert "\n".join(parts) == text


# --- config ----------------------------------------------------------------


def test_load_settings():
    settings = load_settings(
        {"BOT_TOKEN": "t", "ADMIN_TELEGRAM_IDS": "1, 2;3", "ALLOWED_CHAT_IDS": "-100"}
    )
    assert settings.admin_ids == frozenset({1, 2, 3})
    assert settings.allowed_chat_ids == frozenset({-100})
    assert settings.log_level == "INFO"


@pytest.mark.parametrize(
    "env",
    [
        {"ADMIN_TELEGRAM_IDS": "1"},
        {"BOT_TOKEN": "t", "ADMIN_TELEGRAM_IDS": "abc"},
    ],
)
def test_load_settings_errors(env):
    with pytest.raises(ConfigurationError):
        load_settings(env)


def test_first_start_without_admins_is_allowed():
    # Nobody has access yet; the bot tells people their ID via /whoami.
    assert load_settings({"BOT_TOKEN": "t"}).admin_ids == frozenset()


def test_load_settings_without_bot():
    assert load_settings({}, require_bot=False).bot_token is None


# --- roles -----------------------------------------------------------------


def test_role_resolver_with_cache():
    db = InMemoryDatabase()
    db.seed("client_info", "main_client", {"telegram_id": 2002, "balance": 0})
    now = [0.0]
    resolver = RoleResolver(
        db, ClientRepository(), frozenset({1001}), cache_ttl_seconds=60, monotonic=lambda: now[0]
    )

    assert resolver.resolve(1001) is Role.ADMIN
    assert resolver.resolve(2002) is Role.CLIENT
    assert resolver.resolve(3003) is None

    db.seed("client_info", "main_client", {"telegram_id": 3003, "balance": 0})
    assert resolver.resolve(3003) is None  # cached
    now[0] = 61
    assert resolver.resolve(3003) is Role.CLIENT
    assert resolver.resolve(2002) is None


def test_role_resolver_without_client_document():
    resolver = RoleResolver(InMemoryDatabase(), ClientRepository(), frozenset({1}))
    assert resolver.resolve(1) is Role.ADMIN
    assert resolver.resolve(2) is None


def test_audience_is_client_outside_private_admin_chat():
    from aiogram.types import Chat

    from crm.bot.access import audience_for

    private = Chat(id=1, type="private")
    group = Chat(id=-100, type="supergroup")
    assert audience_for(Role.ADMIN, private) is Role.ADMIN
    assert audience_for(Role.ADMIN, group) is Role.CLIENT
    assert audience_for(Role.CLIENT, private) is Role.CLIENT
    assert audience_for(None, private) is Role.CLIENT


def test_parse_rebuy():
    assert parsing.parse_rebuy("5 150,000 185000") == ("N5", 150_000, 185_000, None, None)
    assert parsing.parse_rebuy("N5 1 2 https://shop.kr/x Магазин отменил") == (
        "N5",
        1,
        2,
        "https://shop.kr/x",
        "Магазин отменил",
    )
    assert parsing.parse_rebuy("5 1 2 Нет в наличии") == ("N5", 1, 2, None, "Нет в наличии")
    with pytest.raises(ValidationError):
        parsing.parse_rebuy("5 1")


def test_delete_ranges_and_compact_callback_data():
    from crm.bot import parsing

    ids = parsing.parse_order_list("1-3, N5 #10–12 2", parsing.DELETE_USAGE)
    assert ids == ["N1", "N2", "N3", "N5", "N10", "N11", "N12"]
    assert parsing.parse_order_list("5-3", parsing.DELETE_USAGE) == ["N3", "N4", "N5"]
    compact = parsing.compact_order_ids(ids)
    assert compact == "1-3.5.10-12"
    assert parsing.expand_order_ids(compact) == ids
    with pytest.raises(ValidationError):
        parsing.parse_order_list("1-500", parsing.DELETE_USAGE)
    with pytest.raises(ValidationError):
        parsing.parse_order_list("", parsing.DELETE_USAGE)

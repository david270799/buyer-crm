"""Command argument parsing. Pure functions; every error is a ValidationError."""

from decimal import Decimal

from crm.domain.enums import OrderStatus, parse_status
from crm.domain.errors import ValidationError
from crm.domain.ids import normalize_order_id, parse_order_ids, split_tokens
from crm.domain.money import parse_krw, parse_rate

BUY_USAGE = "Формат: /buy <номер> <закупка> <цена клиенту>\nПример: /buy 5 140000 170000"
CANCEL_USAGE = "Формат: /cancel <номер>\nПример: /cancel 125"
ORDER_USAGE = "Формат: /order <номер>\nПример: /order 125"
STATUS_USAGE = (
    "Формат: /status <статус> <номера…>\nПример: /status warehouse 5 7 12\n"
    "Статусы: warehouse (склад), cargo (карго), delivered (доставлен)"
)
CARGO_USAGE = "Формат: /cargo <трек-номер> <номера…>\nПример: /cargo TRACK123 5 10 18"
DEPOSIT_USAGE = "Формат: /deposit <сумма> [комментарий]\nПример: /deposit 5000000 перевод 26.09"
ADJUST_USAGE = "Формат: /adjust <±сумма> <причина>\nПример: /adjust -15000 комиссия банка"
SHIPCOST_USAGE = (
    "Формат: /shipcost <отправка> <стоимость>\nПример: /shipcost 18 95000 или "
    "/shipcost SHP-2026-018 95000"
)
REBUY_USAGE = (
    "Формат: /rebuy <номер> <закупка> <цена клиенту> [ссылка] [причина для клиента]\n"
    "Пример: /rebuy 5 150000 185000 https://shop.kr/item Магазин отменил заказ"
)
RATE_USAGE = "Формат: /rate <KRW за 1 USD>\nПример: /rate 1350"


def _tokens(args: str | None) -> list[str]:
    return split_tokens(args or "")


def _order_ids(tokens: list[str], usage: str) -> list[str]:
    ids, invalid = parse_order_ids(tokens)
    if invalid:
        raise ValidationError(f"Некорректные номера заказов: {', '.join(invalid)}.\n{usage}")
    if not ids:
        raise ValidationError(f"Не указаны номера заказов.\n{usage}")
    return ids


def parse_buy(args: str | None) -> tuple[str, int, int]:
    # Whitespace only: amounts may contain thousands separators ("170,000").
    tokens = (args or "").split()
    if len(tokens) != 3:
        raise ValidationError(BUY_USAGE)
    order_id = normalize_order_id(tokens[0])
    return order_id, parse_krw(tokens[1]), parse_krw(tokens[2])


def parse_single_order(args: str | None, usage: str) -> str:
    tokens = (args or "").split()
    if len(tokens) != 1:
        raise ValidationError(usage)
    return normalize_order_id(tokens[0])


def parse_status_command(args: str | None) -> tuple[OrderStatus, list[str]]:
    tokens = _tokens(args)
    statuses = [(token, parse_status(token)) for token in tokens]
    found = [(token, status) for token, status in statuses if status is not None]
    if len(found) != 1:
        raise ValidationError(STATUS_USAGE)
    status_token, status = found[0]
    rest = [token for token in tokens if token != status_token]
    return status, _order_ids(rest, STATUS_USAGE)


def parse_cargo(args: str | None) -> tuple[str, list[str]]:
    parts = (args or "").split(maxsplit=1)
    if len(parts) < 2:
        raise ValidationError(CARGO_USAGE)
    return parts[0], _order_ids(_tokens(parts[1]), CARGO_USAGE)


def parse_amount_with_comment(
    args: str | None, usage: str, *, allow_negative: bool
) -> tuple[int, str | None]:
    parts = (args or "").split(maxsplit=1)
    if not parts:
        raise ValidationError(usage)
    comment = parts[1].strip() if len(parts) > 1 else ""
    return parse_krw(parts[0], allow_negative=allow_negative), comment or None


def parse_rate_command(args: str | None) -> Decimal | None:
    tokens = (args or "").split()
    if not tokens:
        return None
    if len(tokens) != 1:
        raise ValidationError(RATE_USAGE)
    return parse_rate(tokens[0])


def parse_shipcost(args: str | None) -> tuple[str, int]:
    tokens = (args or "").split()
    if len(tokens) != 2:
        raise ValidationError(SHIPCOST_USAGE)
    return tokens[0], parse_krw(tokens[1])


def parse_rebuy(args: str | None) -> tuple[str, int, int, str | None, str | None]:
    parts = (args or "").split(maxsplit=3)
    if len(parts) < 3:
        raise ValidationError(REBUY_USAGE)
    order_id = normalize_order_id(parts[0])
    purchase, price = parse_krw(parts[1]), parse_krw(parts[2])
    rest = parts[3].strip() if len(parts) > 3 else ""
    link = None
    if rest.lower().startswith(("http://", "https://")):
        link, _, rest = rest.partition(" ")
    return order_id, purchase, price, link, rest.strip() or None

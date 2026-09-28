"""Command argument parsing. Pure functions; every error is a ValidationError."""

import re
from decimal import Decimal

from crm.domain.enums import OrderStatus, parse_status
from crm.domain.errors import ValidationError
from crm.domain.ids import normalize_order_id, order_number, parse_order_ids, split_tokens
from crm.domain.money import parse_krw, parse_rate
from crm.services.common import MAX_BULK_ORDERS

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
DELETE_USAGE = (
    "Формат: /delete <номера…>\nПример: /delete 7 или /delete 1-5 8\n"
    "Заказ удаляется отовсюду; списанное по нему возвращается на баланс."
)
PROFIT_USAGE = (
    "Формат: /profit <±сумма> [комментарий]\nПример: /profit 50000 кэшбэк магазина\n"
    "Прибыль видите только вы; баланс клиента не меняется."
)
RATE_USAGE = "Формат: /rate <KRW за 1 USD>\nПример: /rate 1350"
NOTIFY_USAGE = (
    "Формат: /notify [off | me | client] [important | all]\n"
    "Пример: /notify me all — все уведомления только вам, для проверки"
)

_NOTIFY_WORDS = {
    "off": ("recipient", "off"),
    "выкл": ("recipient", "off"),
    "me": ("recipient", "admins"),
    "мне": ("recipient", "admins"),
    "admins": ("recipient", "admins"),
    "client": ("recipient", "client"),
    "клиенту": ("recipient", "client"),
    "important": ("level", "important"),
    "важные": ("level", "important"),
    "all": ("level", "all"),
    "все": ("level", "all"),
}


def _tokens(args: str | None) -> list[str]:
    return split_tokens(args or "")


def _order_ids(tokens: list[str], usage: str) -> list[str]:
    ids, invalid = parse_order_ids(tokens)
    if invalid:
        raise ValidationError(f"Некорректные номера заказов: {', '.join(invalid)}.\n{usage}")
    if not ids:
        raise ValidationError(f"Не указаны номера заказов.\n{usage}")
    return ids


_RANGE_RE = re.compile(r"^([nN#№]?\d+)\s*[-–—]\s*([nN#№]?\d+)$")


def parse_order_list(args: str | None, usage: str) -> list[str]:
    """Order numbers with ranges: `1-5 8` → N1…N5, N8."""
    tokens: list[str] = []
    # "1 - 5" → "1-5"
    for token in _tokens(re.sub(r"\s*[-–—]\s*", "-", args or "")):
        match = _RANGE_RE.match(token)
        if not match:
            tokens.append(token)
            continue
        first, last = (order_number(normalize_order_id(t)) or 0 for t in match.groups())
        if first > last:
            first, last = last, first
        if last - first >= MAX_BULK_ORDERS:
            raise ValidationError(
                f"Слишком большой диапазон {token}: не больше {MAX_BULK_ORDERS} заказов за раз."
            )
        tokens += [str(n) for n in range(first, last + 1)]
    return _order_ids(tokens, usage)


def compact_order_ids(order_ids: list[str]) -> str:
    """`N1 N2 N3 N5` → `1-3.5` (for 64-byte Telegram callback data)."""
    numbers = sorted({order_number(i) or 0 for i in order_ids})
    parts: list[str] = []
    start = prev = None
    for n in [*numbers, None]:
        if n is not None and prev is not None and n == prev + 1:
            prev = n
            continue
        if start is not None:
            parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = n
    return ".".join(parts)


def expand_order_ids(compact: str) -> list[str]:
    """Inverse of `compact_order_ids`."""
    return parse_order_list(compact.replace(".", " "), DELETE_USAGE)


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


def parse_notify(args: str | None) -> dict[str, str]:
    """`/notify me all` → {"recipient": "admins", "level": "all"}; empty → {}."""
    result: dict[str, str] = {}
    for token in (args or "").lower().split():
        field = _NOTIFY_WORDS.get(token)
        if field is None or field[0] in result:
            raise ValidationError(NOTIFY_USAGE)
        result[field[0]] = field[1]
    return result

"""KRW amounts are integers (the won has no minor unit). USD is display-only."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from crm.domain.errors import ValidationError

# Sanity cap for a single operation: catches typos such as an extra zero block.
MAX_AMOUNT_KRW = 1_000_000_000

MIN_KRW_PER_USD = Decimal("100")
MAX_KRW_PER_USD = Decimal("10000")

_AMOUNT_RE = re.compile(r"^([+-]?)₩?(\d{1,3}(?:[,_]\d{3})+|\d+)$")


def parse_krw(token: str, *, allow_negative: bool = False) -> int:
    match = _AMOUNT_RE.match(token.strip())
    if not match:
        raise ValidationError(
            f"Некорректная сумма: «{token}». Укажите целое число вонов, например 170000."
        )
    sign, digits = match.groups()
    amount = int(digits.replace(",", "").replace("_", ""))
    if sign == "-":
        if not allow_negative:
            raise ValidationError(f"Сумма не может быть отрицательной: «{token}».")
        amount = -amount
    if abs(amount) > MAX_AMOUNT_KRW:
        raise ValidationError(
            f"Сумма {format_krw(amount)} больше допустимого лимита {format_krw(MAX_AMOUNT_KRW)}."
        )
    return amount


def parse_rate(token: str) -> Decimal:
    try:
        rate = Decimal(token.strip().replace(",", "."))
    except InvalidOperation:
        raise ValidationError(f"Некорректный курс: «{token}». Пример: 1350.") from None
    if not rate.is_finite() or not (MIN_KRW_PER_USD <= rate <= MAX_KRW_PER_USD):
        raise ValidationError(
            f"Курс должен быть между {MIN_KRW_PER_USD} и {MAX_KRW_PER_USD} KRW за 1 USD."
        )
    return rate


def to_int_amount(value: object) -> int | None:
    """Read a stored money value leniently (legacy docs may hold floats or strings)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value)) if value == value and abs(value) != float("inf") else None
    if isinstance(value, str):
        try:
            return parse_krw(value, allow_negative=True)
        except ValidationError:
            return None
    return None


def krw_to_usd(amount_krw: int, krw_per_usd: Decimal) -> Decimal:
    return Decimal(amount_krw) / krw_per_usd


def _group(value: int) -> str:
    return f"{value:,}"


def format_krw(amount: int, *, signed: bool = False) -> str:
    """`₩ 170,000`, `- ₩ 2,400,000`; with signed=True positive values get `+`."""
    if amount < 0:
        return f"- ₩ {_group(-amount)}"
    return f"+ ₩ {_group(amount)}" if signed and amount > 0 else f"₩ {_group(amount)}"


def format_usd(amount: Decimal) -> str:
    whole = int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"- $ {_group(-whole)}" if whole < 0 else f"$ {_group(whole)}"

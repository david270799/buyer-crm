"""Order ID normalisation: `5`, `n5`, `N05`, `#5` all mean document `n5`."""

import re

from crm.domain.errors import ValidationError

_ORDER_TOKEN_RE = re.compile(r"^[nN#№]?0*([1-9]\d{0,6})$")
_ORDER_DOC_ID_RE = re.compile(r"^n([1-9]\d*)$")
_SPLIT_RE = re.compile(r"[\s,;]+")
_TRACKING_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,63}$")


def normalize_order_id(token: str) -> str:
    match = _ORDER_TOKEN_RE.match(token.strip())
    if not match:
        raise ValidationError(f"Некорректный номер заказа: «{token}». Пример: 5 или n5.")
    return f"n{match.group(1)}"


def order_number(order_id: str) -> int | None:
    """Numeric part of a canonical order document ID, or None for other IDs."""
    match = _ORDER_DOC_ID_RE.match(order_id)
    return int(match.group(1)) if match else None


def make_order_id(number: int) -> str:
    return f"n{number}"


def normalize_tracking_code(raw: str) -> str:
    code = raw.strip().upper()
    if not _TRACKING_RE.match(code):
        raise ValidationError(
            f"Некорректный трек-номер: «{raw}». Допустимы латинские буквы, цифры и дефис, "
            "от 3 до 64 символов."
        )
    return code


def make_shipment_id(year: int, number: int) -> str:
    return f"SHP-{year}-{number:03d}"


def split_tokens(text: str) -> list[str]:
    return [token for token in _SPLIT_RE.split(text.strip()) if token]


def parse_order_ids(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Return (unique normalised IDs in input order, tokens that are not IDs)."""
    ids: list[str] = []
    invalid: list[str] = []
    for token in tokens:
        try:
            order_id = normalize_order_id(token)
        except ValidationError:
            invalid.append(token)
            continue
        if order_id not in ids:
            ids.append(order_id)
    return ids, invalid

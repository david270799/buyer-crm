"""Timestamps are stored in UTC; people see them in Asia/Seoul."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo("Asia/Seoul")

_MONTHS_RU = (
    "янв",
    "фев",
    "мар",
    "апр",
    "мая",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
)


def to_local(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BUSINESS_TZ)


def format_date(value: datetime | None) -> str:
    if value is None:
        return "—"
    local = to_local(value)
    return f"{local.day} {_MONTHS_RU[local.month - 1]} {local.year}"


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    local = to_local(value)
    return f"{format_date(local)}, {local:%H:%M}"

"""Telegram notifications about events, sent by the bot to a private chat.

Every event is written with `delivery = "pending"` in the same transaction
as the change it describes (an outbox). The bot process picks pending events
up, sends them and records the outcome on the event, so a restart neither
loses nor repeats a notification.

The owner decides who receives them (nobody / the admins, to try it out /
the client) and what (important only / everything). Texts are the same
client-safe event texts the bell shows.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class NotifyRecipient(StrEnum):
    OFF = "off"
    ADMINS = "admins"  # to see how notifications look before the client gets them
    CLIENT = "client"


class NotifyLevel(StrEnum):
    IMPORTANT = "important"
    ALL = "all"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    SKIPPED = "skipped"
    FAILED = "failed"


RECIPIENT_LABELS = {
    NotifyRecipient.OFF: "выключены",
    NotifyRecipient.ADMINS: "только мне (проверка)",
    NotifyRecipient.CLIENT: "клиенту",
}

LEVEL_LABELS = {
    NotifyLevel.IMPORTANT: "только важные",
    NotifyLevel.ALL: "все",
}


def _dt(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _enum(kind: type[StrEnum], value: Any, default: StrEnum) -> Any:
    try:
        return kind(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class NotificationSettings:
    recipient: NotifyRecipient = NotifyRecipient.OFF
    level: NotifyLevel = NotifyLevel.IMPORTANT
    # Events created before the recipient was last changed are never sent:
    # switching notifications on must not replay the backlog.
    since: datetime | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None
    last_sent_at: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None

    @classmethod
    def from_doc(cls, data: dict[str, Any] | None) -> "NotificationSettings":
        if not data:
            return cls()
        error = data.get("last_error")
        return cls(
            recipient=_enum(NotifyRecipient, data.get("recipient"), NotifyRecipient.OFF),
            level=_enum(NotifyLevel, data.get("level"), NotifyLevel.IMPORTANT),
            since=_dt(data.get("since")),
            updated_at=_dt(data.get("updated_at")),
            updated_by=data.get("updated_by") if isinstance(data.get("updated_by"), str) else None,
            last_sent_at=_dt(data.get("last_sent_at")),
            last_error=error if isinstance(error, str) and error else None,
            last_error_at=_dt(data.get("last_error_at")),
        )

    @property
    def has_recent_error(self) -> bool:
        """The last attempt failed (no successful send after the error)."""
        if self.last_error_at is None:
            return False
        return self.last_sent_at is None or self.last_sent_at < self.last_error_at

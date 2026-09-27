"""Who receives Telegram notifications, and the bookkeeping of what was sent.

Sending itself lives in the bot (crm.bot.notifier); this service decides
which pending events go to which chats and records the outcome, so the rules
are testable without Telegram.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from crm.domain.errors import ValidationError
from crm.domain.events import Event
from crm.domain.notifications import (
    DeliveryStatus,
    NotificationSettings,
    NotifyLevel,
    NotifyRecipient,
)
from crm.repositories import ClientRepository, EventRepository, SettingsRepository
from crm.services.common import UNSET, Actor, Auditor, Clock, require_admin
from crm.services.events import EventRecorder
from crm.storage import Database, DocumentMissingError, Transaction

MAX_ATTEMPTS = 5
# A notification that could not go out for a day is no longer news.
MAX_AGE = timedelta(hours=24)
_MAX_ERROR = 300


@dataclass(frozen=True)
class Delivery:
    event: Event
    chat_ids: tuple[int, ...]


@dataclass(frozen=True)
class DueBatch:
    deliveries: list[Delivery]
    # The page was full: more pending events may be waiting.
    more: bool


@dataclass(frozen=True)
class SendOutcome:
    chat_id: int
    ok: bool
    # True when retrying cannot help: the user blocked the bot or never opened it.
    permanent: bool = False
    error: str | None = None


def _skip_reason(
    event: Event, settings: NotificationSettings, chat_ids: tuple[int, ...], now: datetime
) -> str | None:
    if settings.recipient is NotifyRecipient.OFF:
        return "off"
    if settings.level is NotifyLevel.IMPORTANT and not event.important:
        return "level"
    if event.created_at is None:
        return "no_time"
    if settings.since is not None and event.created_at < settings.since:
        return "before_enabled"
    if now - event.created_at > MAX_AGE:
        return "too_old"
    if not chat_ids:
        return "no_recipient"
    return None


class NotificationService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        events: EventRepository,
        settings: SettingsRepository,
        clients: ClientRepository,
        recorder: EventRecorder,
        auditor: Auditor,
        admin_ids: frozenset[int],
    ):
        self._db = db
        self._clock = clock
        self._events = events
        self._settings = settings
        self._clients = clients
        self._recorder = recorder
        self._auditor = auditor
        self._admin_ids = admin_ids

    # --- settings (admin) --------------------------------------------------

    def get_settings(self, actor: Actor) -> NotificationSettings:
        require_admin(actor)
        return self._settings.get_notifications(self._db)

    def client_has_telegram(self, actor: Actor) -> bool:
        require_admin(actor)
        client = self._clients.get_main(self._db)
        return client is not None and client.telegram_id is not None

    def update_settings(
        self, actor: Actor, *, recipient: Any = UNSET, level: Any = UNSET
    ) -> NotificationSettings:
        require_admin(actor)
        changes: dict[str, Any] = {}
        if recipient is not UNSET:
            try:
                changes["recipient"] = NotifyRecipient(recipient).value
            except ValueError:
                raise ValidationError("Получатель: off, admins или client.") from None
        if level is not UNSET:
            try:
                changes["level"] = NotifyLevel(level).value
            except ValueError:
                raise ValidationError("Уровень: important или all.") from None

        def fn(tx: Transaction) -> NotificationSettings:
            before = self._settings.get_notifications(tx)
            new_recipient = NotifyRecipient(changes.get("recipient", before.recipient))
            new_level = NotifyLevel(changes.get("level", before.level))
            if new_recipient is before.recipient and new_level is before.level:
                return before
            now = self._clock.now()
            data: dict[str, Any] = {
                "recipient": new_recipient.value,
                "level": new_level.value,
                "updated_at": now,
                "updated_by": actor.id,
            }
            if new_recipient is not before.recipient:
                data["since"] = now
            self._settings.set_notifications(tx, data)
            self._auditor.record(
                tx,
                actor,
                now,
                action="settings.notifications",
                entity_type="settings",
                entity_id="notifications",
                before={"recipient": before.recipient.value, "level": before.level.value},
                after={"recipient": new_recipient.value, "level": new_level.value},
            )
            return replace(
                before,
                recipient=new_recipient,
                level=new_level,
                since=data.get("since", before.since),
                updated_at=now,
                updated_by=actor.id,
            )

        return self._db.run_transaction(fn)

    # --- delivery (bot process) --------------------------------------------

    def listen(self, callback: Callable[[], None]) -> None:
        self._recorder.add_listener(callback)

    def unlisten(self, callback: Callable[[], None]) -> None:
        self._recorder.remove_listener(callback)

    def _chat_ids(self, settings: NotificationSettings) -> tuple[int, ...]:
        if settings.recipient is NotifyRecipient.ADMINS:
            return tuple(sorted(self._admin_ids))
        if settings.recipient is NotifyRecipient.CLIENT:
            client = self._clients.get_main(self._db)
            if client is not None and client.telegram_id is not None:
                return (client.telegram_id,)
        return ()

    def due(self, limit: int = 50) -> DueBatch:
        """Pending events to send now, oldest first. Events that must not be
        sent (switched off, below the level, too old) are marked skipped."""
        settings = self._settings.get_notifications(self._db)
        pending = self._events.pending_delivery(self._db, limit)
        if not pending:
            return DueBatch(deliveries=[], more=False)
        chat_ids = self._chat_ids(settings)
        now = self._clock.now()
        deliveries = []
        for event in pending:
            reason = _skip_reason(event, settings, chat_ids, now)
            if reason is not None:
                self._finish(
                    event.id, {"delivery": DeliveryStatus.SKIPPED.value, "delivery_note": reason}
                )
                continue
            remaining = tuple(c for c in chat_ids if c not in event.delivered_to)
            if remaining:
                deliveries.append(Delivery(event, remaining))
            else:
                self._finish(event.id, {"delivery": DeliveryStatus.SENT.value})
        return DueBatch(deliveries=deliveries, more=len(pending) == limit)

    def record(self, delivery: Delivery, outcomes: list[SendOutcome]) -> DeliveryStatus:
        event = delivery.event
        now = self._clock.now()
        sent = [*event.delivered_to, *(o.chat_id for o in outcomes if o.ok)]
        errors = [o for o in outcomes if not o.ok]
        attempts = event.delivery_attempts + 1
        if any(not o.permanent for o in errors) and attempts < MAX_ATTEMPTS:
            status = DeliveryStatus.PENDING
        elif errors and not sent:
            status = DeliveryStatus.FAILED
        else:
            status = DeliveryStatus.SENT
        data: dict[str, Any] = {
            "delivery": status.value,
            "delivery_attempts": attempts,
            "delivered_to": sent,
        }
        if errors:
            data["delivery_note"] = (errors[0].error or "error")[:_MAX_ERROR]
        if status is DeliveryStatus.SENT:
            data["delivered_at"] = now
        self._finish(event.id, data)

        state: dict[str, Any] = {}
        if any(o.ok for o in outcomes):
            state["last_sent_at"] = now
        if errors:
            state.update(last_error=data["delivery_note"], last_error_at=now)
        if state:
            self._db.run_transaction(lambda tx: self._settings.set_notifications(tx, state))
        return status

    def _finish(self, event_id: str, data: dict[str, Any]) -> None:
        try:
            self._db.run_transaction(lambda tx: self._events.set_delivery(tx, event_id, data))
        except DocumentMissingError:
            pass  # removed by hand in the console: nothing left to deliver

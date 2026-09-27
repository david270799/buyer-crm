"""Events: written inside business transactions, read by the Mini App."""

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from crm.domain.events import Event, EventType, is_important
from crm.domain.ids import normalize_order_id
from crm.repositories import EventReadsRepository, EventRepository
from crm.services.common import Actor, Clock
from crm.storage import Database, Transaction

_PAGE = 100
_MAX_PAGES = 5
UNREAD_CAP = 99


class EventRecorder:
    """Used by services within their transaction (write phase)."""

    def __init__(self, db: Database, repo: EventRepository):
        self._db = db
        self._repo = repo
        self._lock = threading.Lock()
        self._last: datetime | None = None

    def _stamp(self, now: datetime) -> datetime:
        # Strictly increasing timestamps keep "before" pagination exact even
        # when one operation records several events at the same instant.
        with self._lock:
            if self._last is not None and now <= self._last:
                now = self._last + timedelta(microseconds=1)
            self._last = now
            return now

    def record(
        self,
        tx: Transaction,
        actor: Actor,
        now: datetime,
        type: EventType,
        title: str,
        *,
        body: str | None = None,
        order_ids: Sequence[str] = (),
        shipment_id: str | None = None,
        amount_krw: int | None = None,
    ) -> None:
        self._repo.create(
            tx,
            self._db.new_id(),
            {
                "type": type.value,
                "important": is_important(type),
                "title": title,
                "body": body,
                "order_ids": list(order_ids),
                "shipment_id": shipment_id,
                "amount_krw": amount_krw,
                "created_at": self._stamp(now),
                "actor": actor.id,
            },
        )


@dataclass(frozen=True)
class Unread:
    important: int
    total: int
    seen_at: datetime | None = None


class EventService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        events: EventRepository,
        reads: EventReadsRepository,
    ):
        self._db = db
        self._clock = clock
        self._events = events
        self._reads = reads

    def feed(
        self,
        actor: Actor,
        *,
        important_only: bool = False,
        before: datetime | None = None,
        limit: int = 30,
    ) -> list[Event]:
        """Newest first. "Important" is filtered here, page by page, so the
        query needs no composite index."""
        limit = max(1, min(limit, 100))
        result: list[Event] = []
        cursor = before
        for _ in range(_MAX_PAGES):
            page = self._events.page(self._db, before=cursor, limit=_PAGE)
            result.extend(e for e in page if e.important or not important_only)
            if len(result) >= limit or len(page) < _PAGE:
                break
            cursor = page[-1].created_at
        return result[:limit]

    def unread(self, actor: Actor) -> Unread:
        seen = self._reads.seen_at(self._db, actor.id)
        recent = self._events.page(self._db, after=seen, limit=UNREAD_CAP + 1)
        return Unread(
            important=min(sum(1 for e in recent if e.important), UNREAD_CAP),
            total=min(len(recent), UNREAD_CAP),
            seen_at=seen,
        )

    def mark_read(self, actor: Actor) -> None:
        now = self._clock.now()
        self._db.run_transaction(lambda tx: self._reads.mark(tx, actor.id, now))

    def for_order(self, actor: Actor, order_id: str) -> list[Event]:
        return self._events.for_order(self._db, normalize_order_id(order_id))

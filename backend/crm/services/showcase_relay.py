"""Orders from «Витрина» told to the admin and copied to the orders channel
(the owner, 05.11.2026): the bot writes to the admin privately («пришёл заказ»)
and posts the card's first photo with the size to the channel the orders
usually come from. That post becomes the order's message: its reaction then
follows the status like any other order.

An outbox, like the notifier's: the order is created with `relay: pending`
in its own transaction; the bot worker sends and records each step, so a
restart neither loses nor repeats a post.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from crm.repositories import IntakeRepository
from crm.services.common import Clock
from crm.services.events import EventRecorder
from crm.services.group_service import GroupService
from crm.storage import Database, Transaction

PENDING, POSTED, SENT = "pending", "posted", "sent"
ORDERS = "orders"


@dataclass(frozen=True)
class RelayTask:
    order_id: str
    state: str
    brand: str | None
    model: str | None
    size: str | None
    size_kr: str | None
    client_price: int | None
    photo_url: str | None
    by_client: bool

    @property
    def title(self) -> str:
        return " ".join(p for p in (self.brand, self.model) if p) or "Без названия"

    @property
    def size_line(self) -> str | None:
        sizes = [s for s in (self.size, self.size_kr) if s]
        return " / ".join(dict.fromkeys(sizes)) or None


class ShowcaseRelayService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        recorder: EventRecorder,
        groups: GroupService,
        admin_chat: Callable[[], int | None] = lambda: None,
    ):
        self._db = db
        self._clock = clock
        self._recorder = recorder
        self._groups = groups
        self._admin_chat = admin_chat
        self._intake = IntakeRepository()

    def listen(self, callback: Callable[[], None]) -> None:
        self._recorder.add_listener(callback)

    def unlisten(self, callback: Callable[[], None]) -> None:
        self._recorder.remove_listener(callback)

    def pending(self) -> list[RelayTask]:
        tasks = []
        for order_id, doc in self._db.scan(ORDERS):
            state = doc.get("relay")
            if state not in (PENDING, POSTED):
                continue
            tasks.append(
                RelayTask(
                    order_id,
                    state,
                    doc.get("brand"),
                    doc.get("model"),
                    doc.get("size"),
                    doc.get("size_kr"),
                    doc.get("client_price"),
                    doc.get("photo_url"),
                    doc.get("relay_by") == "client",
                )
            )
        return sorted(tasks, key=lambda t: _number(t.order_id))

    def orders_chat(self) -> int | None:
        """The channel the orders usually come from: the one of the latest
        order sent there; else the only allowed chat."""
        admin_chat = self._admin_chat()
        latest: tuple[datetime, int] | None = None
        for _, doc in self._db.scan(ORDERS):
            chat, at = doc.get("source_chat_id"), doc.get("created_at")
            if not isinstance(chat, int) or chat >= 0 or chat == admin_chat or doc.get("relay"):
                continue
            if isinstance(at, datetime) and (latest is None or at > latest[0]):
                latest = (at, chat)
        if latest is not None:
            return latest[1]
        allowed = [c for c in self._groups.allowed_ids() if c < 0 and c != admin_chat]
        return allowed[0] if len(allowed) == 1 else None

    def posted(self, order_id: str, chat_id: int | None, message_id: int | None) -> None:
        """The channel step is over: the post (if any) becomes the order's message."""
        now = self._clock.now()

        def fn(tx: Transaction) -> None:
            doc = tx.get(ORDERS, order_id)
            if doc is None or doc.get("relay") != PENDING:
                return
            change: dict[str, Any] = {"relay": POSTED}
            if (
                chat_id is not None
                and message_id is not None
                and doc.get("source_message_id") is None
            ):
                key = self._intake.key(chat_id, message_id)
                if tx.get(self._intake.collection, key) is None:
                    self._intake.create(
                        tx, key, order_id=order_id, chat_id=chat_id, message_id=message_id, now=now
                    )
                change.update(source_chat_id=chat_id, source_message_id=message_id)
            tx.update(ORDERS, order_id, change)
            self._recorder.touched(tx)  # the reaction syncer picks the new message up

        self._db.run_transaction(fn)

    def sent(self, order_id: str) -> None:
        def fn(tx: Transaction) -> None:
            doc = tx.get(ORDERS, order_id)
            if doc is not None and doc.get("relay") in (PENDING, POSTED):
                tx.update(ORDERS, order_id, {"relay": SENT})

        self._db.run_transaction(fn)


def _number(order_id: str) -> int:
    digits = "".join(c for c in order_id if c.isdigit())
    return int(digits) if digits else 0

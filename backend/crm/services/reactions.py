"""Reactions on the client's order photo in the group, by order status.

The client looks at the group rather than the CRM: 👍 on a photo means "bought",
then it changes with the status. A new order has no reaction; a cancelled or
deleted one loses it. The bot still writes nothing in the group.

`reactions/tg{chat}_{message}` remembers what was set, so the syncer only
calls Telegram for what changed. Everything is derived from the orders on
each pass, so no business operation has to know about reactions.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from crm.domain.enums import OrderStatus
from crm.repositories import OrderRepository
from crm.services.common import Clock
from crm.services.events import EventRecorder
from crm.storage import Database, Transaction

# The owner's choice first; Telegram lets bots use only its standard reaction
# set, so each status has fallbacks from that set.
STATUS_REACTIONS: dict[OrderStatus, tuple[str, ...]] = {
    OrderStatus.BOUGHT: ("👍",),
    OrderStatus.WAREHOUSE: ("🏠", "👌"),
    OrderStatus.CARGO: ("✈️", "🕊"),
    OrderStatus.DELIVERED: ("✅", "💯"),
}

COLLECTION = "reactions"


def reaction_key(chat_id: int, message_id: int) -> str:
    return f"tg{chat_id}_{message_id}"


@dataclass(frozen=True)
class ReactionTask:
    key: str
    chat_id: int
    message_id: int
    order_id: str | None
    # Status the reaction should show; None: remove the reaction.
    status: str | None
    candidates: tuple[str, ...]
    # What the bot set last time, to try it first (Telegram accepted it before).
    current: str | None = None


class ReactionService:
    def __init__(
        self, db: Database, clock: Clock, orders: OrderRepository, recorder: EventRecorder
    ):
        self._db = db
        self._clock = clock
        self._orders = orders
        self._recorder = recorder

    def listen(self, callback: Callable[[], None]) -> None:
        self._recorder.add_listener(callback)

    def unlisten(self, callback: Callable[[], None]) -> None:
        self._recorder.remove_listener(callback)

    def pending(self) -> list[ReactionTask]:
        sent = dict(self._db.scan(COLLECTION))
        tasks: list[ReactionTask] = []
        seen: set[str] = set()
        for order in self._orders.list_all(self._db):
            if order.source_chat_id is None or order.source_message_id is None:
                continue
            key = reaction_key(order.source_chat_id, order.source_message_id)
            seen.add(key)
            candidates = STATUS_REACTIONS.get(order.status) if order.status else None
            want = order.status.value if candidates and order.status else None
            doc = sent.get(key)
            if doc is None and want is None:
                continue
            if doc is not None and doc.get("status") == want and doc.get("order_id") == order.id:
                continue
            tasks.append(
                ReactionTask(
                    key,
                    order.source_chat_id,
                    order.source_message_id,
                    order.id,
                    want,
                    candidates or (),
                    (doc or {}).get("emoji"),
                )
            )
        for key, doc in sent.items():
            if key in seen:
                continue
            chat_id, message_id = doc.get("chat_id"), doc.get("message_id")
            if isinstance(chat_id, int) and isinstance(message_id, int):
                tasks.append(ReactionTask(key, chat_id, message_id, None, None, ()))
        return tasks

    def record(self, task: ReactionTask, emoji: str | None, error: str | None = None) -> None:
        """Remember the outcome: a failed attempt is not retried until the status changes."""
        now: datetime = self._clock.now()

        def fn(tx: Transaction) -> None:
            if task.status is None:
                tx.delete(COLLECTION, task.key)
                return
            tx.set(
                COLLECTION,
                task.key,
                {
                    "chat_id": task.chat_id,
                    "message_id": task.message_id,
                    "order_id": task.order_id,
                    "status": task.status,
                    "emoji": emoji,
                    "error": error,
                    "updated_at": now,
                },
            )

        self._db.run_transaction(fn)

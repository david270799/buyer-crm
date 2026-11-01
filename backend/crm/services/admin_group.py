"""The admin's own group with topics (the owner, 01.11.2026).

The owner made a supergroup with topics («Склад», «Витрина», «Уведомления»)
and moved the work with the bot there: photos of arrived parcels go to «Склад»,
shop links and screenshots to «Витрина», and everything the bot used to write
to the admins privately lands in «Уведомления». `/topic` sent inside a topic
tells the bot what that topic is for (by its name, or `/topic склад`).

`settings/admin_group` = {"chat_id": int, "title": str, "topics": {kind: thread id}}.
There is one such group: binding a topic of another group starts over.
Only admins are expected in it, so the bot answers there as to an admin.
"""

from dataclasses import dataclass, field

from crm.domain.errors import ValidationError
from crm.services.common import Actor, Auditor, Clock, require_admin
from crm.storage import Database, Transaction

COLLECTION = "settings"
DOC_ID = "admin_group"

WAREHOUSE = "warehouse"
SHOWCASE = "showcase"
NOTIFICATIONS = "notifications"
KINDS = {WAREHOUSE: "Склад", SHOWCASE: "Витрина", NOTIFICATIONS: "Уведомления"}

# Words in a topic name (or after /topic) → its kind. «Ветрина» is how the
# owner named the topic, so both spellings count.
_WORDS = {
    WAREHOUSE: ("склад", "warehouse", "arriv"),
    SHOWCASE: ("витрин", "ветрин", "showcase", "shop"),
    NOTIFICATIONS: ("уведом", "оповещ", "notif"),
}


def kind_from_text(text: str | None) -> str | None:
    low = (text or "").lower()
    for kind, words in _WORDS.items():
        if any(word in low for word in words):
            return kind
    return None


@dataclass(frozen=True)
class AdminGroup:
    chat_id: int | None = None
    title: str | None = None
    topics: dict[str, int] = field(default_factory=dict)

    def topic(self, kind: str) -> int | None:
        """Thread id of the topic for `kind`, or None when it is not bound."""
        return self.topics.get(kind) if self.chat_id is not None else None

    def kind_of(self, chat_id: int, thread_id: int | None) -> str | None:
        """What a message in `chat_id` / `thread_id` is about (None: not ours)."""
        if self.chat_id is None or chat_id != self.chat_id or thread_id is None:
            return None
        for kind, bound in self.topics.items():
            if bound == thread_id:
                return kind
        return None


class AdminGroupService:
    def __init__(self, db: Database, clock: Clock, auditor: Auditor):
        self._db = db
        self._clock = clock
        self._auditor = auditor

    def current(self) -> AdminGroup:
        data = self._db.get(COLLECTION, DOC_ID) or {}
        chat_id = data.get("chat_id")
        topics = data.get("topics")
        return AdminGroup(
            chat_id=int(chat_id) if isinstance(chat_id, int) else None,
            title=data.get("title") if isinstance(data.get("title"), str) else None,
            topics={
                k: int(v) for k, v in (topics or {}).items() if k in KINDS and isinstance(v, int)
            }
            if isinstance(topics, dict)
            else {},
        )

    def bind(
        self, actor: Actor, chat_id: int, title: str | None, thread_id: int | None, kind: str
    ) -> AdminGroup:
        """This topic is «Склад» / «Витрина» / «Уведомления»."""
        require_admin(actor)
        if kind not in KINDS:
            raise ValidationError("Тема: склад, витрина или уведомления.")
        if thread_id is None:
            raise ValidationError("Напишите команду внутри темы (не в General).")
        now = self._clock.now()

        def fn(tx: Transaction) -> None:
            data = tx.get(COLLECTION, DOC_ID) or {}
            same_group = data.get("chat_id") == chat_id
            topics = dict(data.get("topics") or {}) if same_group else {}
            # One topic does one job: a topic moved to another job leaves the old one.
            topics = {k: v for k, v in topics.items() if v != thread_id}
            topics[kind] = thread_id
            tx.set(
                COLLECTION,
                DOC_ID,
                {"chat_id": chat_id, "title": title, "topics": topics, "updated_at": now},
            )
            self._auditor.record(
                tx,
                actor,
                now,
                action="admin_group.bind",
                entity_type="settings",
                entity_id=DOC_ID,
                before={"chat_id": data.get("chat_id"), "topics": data.get("topics")},
                after={"chat_id": chat_id, "topics": topics},
            )

        self._db.run_transaction(fn)
        return self.current()

    def unbind(self, actor: Actor) -> AdminGroup:
        """Forget the group: everything goes back to the admins' private chats."""
        require_admin(actor)
        now = self._clock.now()

        def fn(tx: Transaction) -> None:
            data = tx.get(COLLECTION, DOC_ID) or {}
            tx.set(COLLECTION, DOC_ID, {"chat_id": None, "topics": {}, "updated_at": now})
            self._auditor.record(
                tx,
                actor,
                now,
                action="admin_group.unbind",
                entity_type="settings",
                entity_id=DOC_ID,
                before={"chat_id": data.get("chat_id"), "topics": data.get("topics")},
                after=None,
            )

        self._db.run_transaction(fn)
        return self.current()

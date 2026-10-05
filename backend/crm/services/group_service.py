"""Groups the bot works in, set with /setgroup instead of editing .env.

`settings/groups.chats` = {"<chat id>": title}. Together with ALLOWED_CHAT_IDS
from .env they form the allow-list; when both are empty the bot works in any
group it was added to by an admin (as before).
"""

from crm.services.common import Actor, Auditor, Clock, require_admin
from crm.storage import Database, Transaction

COLLECTION = "settings"
DOC_ID = "groups"


class GroupService:
    def __init__(self, db: Database, clock: Clock, auditor: Auditor, env_ids: frozenset[int]):
        self._db = db
        self._clock = clock
        self._auditor = auditor
        self._env_ids = env_ids

    def _chats(self) -> dict[str, str]:
        data = (self._db.get(COLLECTION, DOC_ID) or {}).get("chats")
        return dict(data) if isinstance(data, dict) else {}

    def allowed_ids(self) -> frozenset[int]:
        """Empty = no restriction."""
        return self._env_ids | {int(i) for i in self._chats()}

    def listing(self, actor: Actor) -> dict[int, str]:
        require_admin(actor)
        chats = {int(i): t for i, t in self._chats().items()}
        for chat_id in self._env_ids:
            chats.setdefault(chat_id, "из .env (ALLOWED_CHAT_IDS)")
        return chats

    def add(self, actor: Actor, chat_id: int, title: str | None) -> dict[int, str]:
        return self._change(actor, chat_id, title or str(chat_id), add=True)

    def remove(self, actor: Actor, chat_id: int) -> dict[int, str]:
        return self._change(actor, chat_id, None, add=False)

    def _change(
        self, actor: Actor, chat_id: int, title: str | None, *, add: bool
    ) -> dict[int, str]:
        require_admin(actor)
        now = self._clock.now()

        def fn(tx: Transaction) -> None:
            data = (tx.get(COLLECTION, DOC_ID) or {}).get("chats")
            chats = dict(data) if isinstance(data, dict) else {}
            if add:
                chats[str(chat_id)] = title
            else:
                chats.pop(str(chat_id), None)
            tx.set(COLLECTION, DOC_ID, {"chats": chats, "updated_at": now}, merge=True)
            self._auditor.record(
                tx,
                actor,
                now,
                action="groups.add" if add else "groups.remove",
                entity_type="settings",
                entity_id=DOC_ID,
                before=None,
                after={"chat_id": chat_id, "title": title},
            )

        self._db.run_transaction(fn)
        return self.listing(actor)

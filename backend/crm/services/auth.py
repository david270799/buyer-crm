"""Role resolution shared by the bot and (later) the Mini App / dashboard API.

ADMIN IDs come from configuration (environment), never from the database.
The CLIENT is whoever `client_info/main_client.telegram_id` points to, and the
second person on the same account (`second_telegram_id`, /setclient2).
For the Mini App the Telegram user ID must come from server-side validated
`initData`, never from `initDataUnsafe`.
"""

import threading
import time
from collections.abc import Callable

from crm.domain.enums import Role
from crm.repositories import ClientRepository
from crm.storage import Database


class RoleResolver:
    def __init__(
        self,
        db: Database,
        clients: ClientRepository,
        admin_ids: frozenset[int],
        cache_ttl_seconds: float = 60.0,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self._db = db
        self._clients = clients
        self._admin_ids = admin_ids
        self._ttl = cache_ttl_seconds
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._client_ids: frozenset[int] = frozenset()
        self._loaded_at: float | None = None

    @property
    def admin_ids(self) -> frozenset[int]:
        return self._admin_ids

    def resolve(self, telegram_user_id: int) -> Role | None:
        if telegram_user_id in self._admin_ids:
            return Role.ADMIN
        if telegram_user_id in self._client_telegram_ids():
            return Role.CLIENT
        return None

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = None

    def _client_telegram_ids(self) -> frozenset[int]:
        with self._lock:
            now = self._monotonic()
            if self._loaded_at is None or now - self._loaded_at > self._ttl:
                client = self._clients.get_main(self._db)
                self._client_ids = frozenset(client.telegram_ids) if client else frozenset()
                self._loaded_at = now
            return self._client_ids

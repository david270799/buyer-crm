"""Who the client is (`client_info/main_client`): set by the admin with /setclient."""

from dataclasses import dataclass, replace

from crm.domain.errors import ConflictError, ValidationError
from crm.domain.models import ClientInfo
from crm.repositories import ClientRepository
from crm.services.auth import RoleResolver
from crm.services.common import Actor, Auditor, Clock, require_admin
from crm.storage import Database, Transaction

_MAX_NAME = 100


@dataclass(frozen=True)
class ClientChange:
    before: ClientInfo | None
    after: ClientInfo


class ClientService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        clients: ClientRepository,
        roles: RoleResolver,
        auditor: Auditor,
    ):
        self._db = db
        self._clock = clock
        self._clients = clients
        self._roles = roles
        self._auditor = auditor

    def set_client(self, actor: Actor, telegram_id: int, name: str | None = None) -> ClientChange:
        """Point the CRM at the client's Telegram account. The balance is kept as is
        (a new client record starts at 0)."""
        require_admin(actor)
        if isinstance(telegram_id, bool) or not isinstance(telegram_id, int) or telegram_id <= 0:
            raise ValidationError("Нужен числовой Telegram ID клиента.")
        if telegram_id in self._roles.admin_ids:
            raise ValidationError("Это ID администратора — клиентом его сделать нельзя.")
        clean_name = " ".join((name or "").split())[:_MAX_NAME] or None

        def fn(tx: Transaction) -> ClientChange:
            before = self._clients.get_main(tx)
            now = self._clock.now()
            keep_name = clean_name or (before.name if before else None)
            self._clients.set_identity(tx, telegram_id, keep_name, now, create=before is None)
            self._auditor.record(
                tx,
                actor,
                now,
                action="client.set",
                entity_type="client",
                entity_id=self._clients.main_client_id,
                before={"telegram_id": before.telegram_id, "name": before.name} if before else None,
                after={"telegram_id": telegram_id, "name": keep_name},
            )
            balance = before.balance if before else 0
            after = ClientInfo(self._clients.main_client_id, telegram_id, keep_name, balance)
            return ClientChange(before=before, after=after)

        change = self._db.run_transaction(fn)
        self._roles.invalidate()  # the new client is recognised right away
        return change

    def get(self, actor: Actor) -> ClientInfo | None:
        require_admin(actor)
        return self._clients.get_main(self._db)

    def set_second(
        self, actor: Actor, telegram_id: int | None, name: str | None = None
    ) -> ClientInfo:
        """/setclient2: a second person on the same account — sees the same orders,
        balance and showcase (the owner, 20.10.2026). None removes them."""
        require_admin(actor)
        if telegram_id is not None:
            if isinstance(telegram_id, bool) or not isinstance(telegram_id, int):
                raise ValidationError("Нужен числовой Telegram ID.")
            if telegram_id <= 0:
                raise ValidationError("Нужен числовой Telegram ID.")
            if telegram_id in self._roles.admin_ids:
                raise ValidationError("Это ID администратора — клиентом его сделать нельзя.")
        clean_name = " ".join((name or "").split())[:_MAX_NAME] or None

        def fn(tx: Transaction) -> ClientInfo:
            before = self._clients.get_main(tx)
            if before is None or before.telegram_id is None:
                raise ConflictError("Сначала укажите основного клиента: /setclient.")
            if telegram_id is not None and telegram_id == before.telegram_id:
                raise ValidationError("Это ID основного клиента — он уже клиент.")
            now = self._clock.now()
            keep_name = clean_name if telegram_id is not None else None
            self._clients.set_second(tx, telegram_id, keep_name, now)
            self._auditor.record(
                tx,
                actor,
                now,
                action="client.set_second",
                entity_type="client",
                entity_id=self._clients.main_client_id,
                before={"second_telegram_id": before.second_telegram_id},
                after={"second_telegram_id": telegram_id, "second_name": keep_name},
            )
            return replace(before, second_telegram_id=telegram_id, second_name=keep_name)

        after = self._db.run_transaction(fn)
        self._roles.invalidate()
        return after

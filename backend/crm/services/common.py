from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from datetime import datetime, timezone
from typing import Any, Protocol

from crm.domain.enums import Role, Source
from crm.domain.errors import PermissionDeniedError, ValidationError
from crm.repositories import AuditRepository
from crm.storage import Database, Transaction

# One Firestore transaction may contain at most 500 writes; each order in a
# bulk operation costs two (the order and its audit entry).
MAX_BULK_ORDERS = 100


class _Unset:
    """Marks a field of a partial update that was not provided (None means "clear")."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()


def provided_fields(update: Any) -> dict[str, Any]:
    """Fields of a partial-update dataclass that are not UNSET."""
    return {
        f.name: getattr(update, f.name)
        for f in dataclass_fields(update)
        if getattr(update, f.name) is not UNSET
    }


@dataclass(frozen=True)
class Actor:
    """Who performs an operation and through which channel."""

    id: str
    role: Role
    source: Source

    @classmethod
    def telegram(cls, user_id: int, role: Role) -> "Actor":
        return cls(id=f"tg:{user_id}", role=role, source=Source.TELEGRAM_BOT)

    @classmethod
    def mini_app(cls, user_id: int, role: Role) -> "Actor":
        return cls(id=f"tg:{user_id}", role=role, source=Source.MINI_APP)

    @classmethod
    def system(cls) -> "Actor":
        return cls(id="system", role=Role.ADMIN, source=Source.SYSTEM)


def require_admin(actor: Actor) -> None:
    if actor.role is not Role.ADMIN:
        raise PermissionDeniedError("Эта операция доступна только администратору.")


def require_bulk_size(ids: list[str]) -> None:
    if not ids:
        raise ValidationError("Не указан ни один заказ.")
    if len(ids) > MAX_BULK_ORDERS:
        raise ValidationError(
            f"За одну операцию можно обработать не больше {MAX_BULK_ORDERS} заказов."
        )


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class Auditor:
    def __init__(self, db: Database, repo: AuditRepository):
        self._db = db
        self._repo = repo

    def record(
        self,
        tx: Transaction,
        actor: Actor,
        now: datetime,
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        self._repo.record(
            tx,
            self._db.new_id(),
            actor=actor.id,
            source=actor.source.value,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
            timestamp=now,
        )

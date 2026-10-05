"""Extra profit the admin records by hand (a shop's cashback, a gain on the
exchange rate, ...). Admin-only: it is added to the profit figures on the
dashboard and never changes or shows in the client's balance."""

import re
from dataclasses import dataclass

from crm.domain.errors import ConflictError, ValidationError
from crm.domain.models import ProfitEntry
from crm.domain.money import MAX_AMOUNT_KRW, format_krw
from crm.repositories import ProfitRepository
from crm.services.common import Actor, Auditor, Clock, require_admin
from crm.storage import Database, Transaction

_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
_MAX_COMMENT = 500


@dataclass(frozen=True)
class ProfitResult:
    entry: ProfitEntry
    already_done: bool


class ProfitService:
    def __init__(self, db: Database, clock: Clock, repo: ProfitRepository, auditor: Auditor):
        self._db = db
        self._clock = clock
        self._repo = repo
        self._auditor = auditor

    def history(self, actor: Actor, limit: int = 50) -> list[ProfitEntry]:
        require_admin(actor)
        return self._repo.list_recent(self._db, max(1, min(limit, 200)))

    def add(
        self,
        actor: Actor,
        amount_krw: int,
        comment: str | None = None,
        idempotency_key: str | None = None,
    ) -> ProfitResult:
        """A positive amount adds profit, a negative one corrects it."""
        require_admin(actor)
        if amount_krw == 0:
            raise ValidationError("Сумма прибыли не может быть нулевой.")
        if abs(amount_krw) > MAX_AMOUNT_KRW:
            raise ValidationError(f"Сумма больше допустимого лимита {format_krw(MAX_AMOUNT_KRW)}.")
        text = (comment or "").strip()
        if len(text) > _MAX_COMMENT:
            raise ValidationError(
                f"Комментарий слишком длинный (максимум {_MAX_COMMENT} символов)."
            )
        if idempotency_key is not None and not _IDEMPOTENCY_KEY_RE.match(idempotency_key):
            raise ValidationError("Некорректный ключ идемпотентности.")
        entry_id = f"profit_{idempotency_key}" if idempotency_key else f"profit_{self._db.new_id()}"

        def fn(tx: Transaction) -> ProfitResult:
            existing = self._repo.get(tx, entry_id)
            if existing is not None:
                if existing.amount_krw != amount_krw:
                    raise ConflictError(
                        "Эта запись уже сделана с другой суммой: "
                        f"{format_krw(existing.amount_krw, signed=True)}."
                    )
                return ProfitResult(existing, already_done=True)
            now = self._clock.now()
            data = {
                "amount_krw": amount_krw,
                "comment": text or None,
                "created_at": now,
                "created_by": actor.id,
                "source": actor.source.value,
            }
            self._repo.create(tx, entry_id, data)
            self._auditor.record(
                tx,
                actor,
                now,
                action="finance.profit",
                entity_type="profit",
                entity_id=entry_id,
                before=None,
                after={"amount_krw": amount_krw, "comment": text or None},
            )
            return ProfitResult(ProfitEntry.from_doc(entry_id, data), already_done=False)

        return self._db.run_transaction(fn)

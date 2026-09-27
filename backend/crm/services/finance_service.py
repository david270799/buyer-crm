import re
from dataclasses import dataclass
from decimal import Decimal

from crm.domain.enums import LedgerType
from crm.domain.errors import ConflictError, ValidationError
from crm.domain.events import EventType
from crm.domain.models import GeneralSettings, LedgerEntry
from crm.domain.money import (
    MAX_AMOUNT_KRW,
    MAX_KRW_PER_USD,
    MIN_KRW_PER_USD,
    format_krw,
    krw_to_usd,
)
from crm.repositories import ClientRepository, LedgerRepository, SettingsRepository
from crm.services.common import Actor, Auditor, Clock, require_admin
from crm.services.events import EventRecorder
from crm.services.ledger import BalanceChange, BalanceLedger
from crm.storage import Database, Transaction

_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
_MAX_COMMENT = 500


@dataclass(frozen=True)
class BalanceView:
    balance_krw: int
    krw_per_usd: Decimal | None

    @property
    def balance_usd(self) -> Decimal | None:
        return krw_to_usd(self.balance_krw, self.krw_per_usd) if self.krw_per_usd else None


@dataclass(frozen=True)
class LedgerResult:
    entry: LedgerEntry
    already_done: bool


def _clean_comment(comment: str | None, *, required: bool) -> str | None:
    text = (comment or "").strip()
    if required and not text:
        raise ValidationError(
            "Для корректировки обязателен комментарий: причина изменения баланса."
        )
    if len(text) > _MAX_COMMENT:
        raise ValidationError(f"Комментарий слишком длинный (максимум {_MAX_COMMENT} символов).")
    return text or None


class FinanceService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        clients: ClientRepository,
        ledger_repo: LedgerRepository,
        settings: SettingsRepository,
        ledger: BalanceLedger,
        auditor: Auditor,
        events: EventRecorder,
    ):
        self._db = db
        self._clock = clock
        self._clients = clients
        self._ledger_repo = ledger_repo
        self._settings = settings
        self._ledger = ledger
        self._auditor = auditor
        self._events = events

    # --- reads (admin and client) -------------------------------------------

    def get_balance(self, actor: Actor) -> BalanceView:
        def fn(tx: Transaction) -> BalanceView:
            client = self._ledger.load_client(tx)
            assert client.balance is not None
            return BalanceView(client.balance, self._settings.get_general(tx).krw_per_usd)

        # A read-only transaction gives a consistent balance + rate pair.
        return self._db.run_transaction(fn)

    def history(self, actor: Actor, limit: int = 20) -> list[LedgerEntry]:
        return self._ledger_repo.list_recent(self._db, limit=max(1, min(limit, 100)))

    def get_settings(self, actor: Actor) -> GeneralSettings:
        return self._settings.get_general(self._db)

    # --- writes (admin only) ------------------------------------------------

    def deposit(
        self,
        actor: Actor,
        amount_krw: int,
        comment: str | None = None,
        idempotency_key: str | None = None,
    ) -> LedgerResult:
        require_admin(actor)
        if amount_krw <= 0:
            raise ValidationError("Сумма пополнения должна быть больше нуля.")
        return self._post(
            actor,
            LedgerType.DEPOSIT,
            amount_krw,
            _clean_comment(comment, required=False),
            idempotency_key,
        )

    def adjust(
        self,
        actor: Actor,
        amount_krw: int,
        comment: str,
        idempotency_key: str | None = None,
    ) -> LedgerResult:
        require_admin(actor)
        if amount_krw == 0:
            raise ValidationError("Сумма корректировки не может быть нулевой.")
        return self._post(
            actor,
            LedgerType.ADJUSTMENT,
            amount_krw,
            _clean_comment(comment, required=True),
            idempotency_key,
        )

    def set_rate(self, actor: Actor, krw_per_usd: Decimal) -> GeneralSettings:
        require_admin(actor)
        if not krw_per_usd.is_finite() or not (MIN_KRW_PER_USD <= krw_per_usd <= MAX_KRW_PER_USD):
            raise ValidationError(
                f"Курс должен быть между {MIN_KRW_PER_USD} и {MAX_KRW_PER_USD} KRW за 1 USD."
            )

        def fn(tx: Transaction) -> GeneralSettings:
            before = self._settings.get_general(tx)
            now = self._clock.now()
            self._settings.set_rate(tx, krw_per_usd, now, actor.id)
            self._auditor.record(
                tx,
                actor,
                now,
                action="settings.rate",
                entity_type="settings",
                entity_id="general",
                before={"krw_per_usd": str(before.krw_per_usd) if before.krw_per_usd else None},
                after={"krw_per_usd": str(krw_per_usd)},
            )
            self._events.record(
                tx,
                actor,
                now,
                EventType.RATE,
                "Обновлён курс доллара",
                body=f"1 $ = {krw_per_usd.normalize():,f} ₩",
            )
            return GeneralSettings(krw_per_usd=krw_per_usd, updated_at=now, updated_by=actor.id)

        return self._db.run_transaction(fn)

    # --- internals ----------------------------------------------------------

    def _post(
        self,
        actor: Actor,
        type: LedgerType,
        amount_krw: int,
        comment: str | None,
        idempotency_key: str | None,
    ) -> LedgerResult:
        if abs(amount_krw) > MAX_AMOUNT_KRW:
            raise ValidationError(f"Сумма больше допустимого лимита {format_krw(MAX_AMOUNT_KRW)}.")
        if idempotency_key is not None and not _IDEMPOTENCY_KEY_RE.match(idempotency_key):
            raise ValidationError("Некорректный ключ идемпотентности.")
        entry_id = f"{type.value}_{idempotency_key}" if idempotency_key else None

        def fn(tx: Transaction) -> LedgerResult:
            if entry_id is not None:
                existing = self._ledger_repo.get(tx, entry_id)
                if existing is not None:
                    if existing.amount_krw != amount_krw:
                        raise ConflictError(
                            "Эта операция уже была выполнена с другой суммой: "
                            f"{format_krw(existing.amount_krw, signed=True)}."
                        )
                    return LedgerResult(existing, already_done=True)
            client = self._ledger.load_client(tx)
            now = self._clock.now()
            change: BalanceChange = self._ledger.apply(
                tx,
                client,
                entry_id=entry_id or f"{type.value}_{self._db.new_id()}",
                type=type,
                amount_krw=amount_krw,
                actor=actor,
                now=now,
                comment=comment,
            )
            self._auditor.record(
                tx,
                actor,
                now,
                action=f"finance.{type.value}",
                entity_type="client",
                entity_id=self._clients.main_client_id,
                before={"balance": change.balance_before},
                after={"balance": change.balance_after, "transaction_id": change.entry_id},
            )
            if type is LedgerType.DEPOSIT:
                self._events.record(
                    tx,
                    actor,
                    now,
                    EventType.DEPOSIT,
                    "Баланс пополнен",
                    body=comment,
                    amount_krw=amount_krw,
                )
            else:
                self._events.record(
                    tx,
                    actor,
                    now,
                    EventType.ADJUSTMENT,
                    "Корректировка баланса",
                    body=comment,
                    amount_krw=amount_krw,
                )
            entry = LedgerEntry(
                id=change.entry_id,
                type=type,
                amount_krw=amount_krw,
                balance_before=change.balance_before,
                balance_after=change.balance_after,
                order_id=None,
                shipment_id=None,
                comment=comment,
                created_at=now,
                created_by=actor.id,
                source=actor.source.value,
            )
            return LedgerResult(entry, already_done=False)

        return self._db.run_transaction(fn)

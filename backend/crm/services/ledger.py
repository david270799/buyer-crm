from dataclasses import dataclass
from datetime import datetime

from crm.domain.enums import LedgerType
from crm.domain.errors import ConfigurationError
from crm.domain.models import ClientInfo
from crm.repositories import ClientRepository, LedgerRepository
from crm.services.common import Actor
from crm.storage import Reader, Transaction


@dataclass(frozen=True)
class BalanceChange:
    entry_id: str
    type: LedgerType
    amount_krw: int
    balance_before: int
    balance_after: int


def order_charge_entry_id(order_id: str) -> str:
    return f"order_charge_{order_id}"


def order_refund_entry_id(order_id: str) -> str:
    return f"order_refund_{order_id}"


class BalanceLedger:
    """The only code path that changes `client_info/main_client.balance`.

    Every change writes the new balance and an append-only `transactions`
    entry in the same Firestore transaction, so the balance can always be
    reconstructed from history. Callers must `load_client` during the read
    phase of their transaction and `apply` during the write phase.
    """

    def __init__(self, clients: ClientRepository, ledger: LedgerRepository):
        self._clients = clients
        self._ledger = ledger

    def load_client(self, tx: Transaction) -> ClientInfo:
        client = self._clients.get_main(tx)
        if client is None:
            raise ConfigurationError(
                "Клиент ещё не назначен: в группе ответьте /setclient на любое сообщение клиента."
            )
        if client.balance is None:
            raise ConfigurationError(
                "Поле balance в client_info/main_client отсутствует или не является числом. "
                "Финансовая операция остановлена."
            )
        return client

    def has_entry(self, reader: Reader, entry_id: str) -> bool:
        return self._ledger.get(reader, entry_id) is not None

    def apply(
        self,
        tx: Transaction,
        client: ClientInfo,
        *,
        entry_id: str,
        type: LedgerType,
        amount_krw: int,
        actor: Actor,
        now: datetime,
        order_id: str | None = None,
        shipment_id: str | None = None,
        comment: str | None = None,
    ) -> BalanceChange:
        assert client.balance is not None  # guaranteed by load_client
        before = client.balance
        after = before + amount_krw
        self._clients.set_balance(tx, after, now)
        self._ledger.create(
            tx,
            entry_id,
            {
                "transaction_id": entry_id,
                "type": type.value,
                "amount_krw": amount_krw,
                "balance_before": before,
                "balance_after": after,
                "order_id": order_id,
                "shipment_id": shipment_id,
                "comment": comment,
                "created_at": now,
                "created_by": actor.id,
                "source": actor.source.value,
            },
        )
        client.balance = after
        return BalanceChange(entry_id, type, amount_krw, before, after)

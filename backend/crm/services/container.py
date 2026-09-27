from dataclasses import dataclass

from crm.repositories import (
    AuditRepository,
    ClientRepository,
    CounterRepository,
    LedgerRepository,
    OrderRepository,
    SettingsRepository,
    ShipmentRepository,
)
from crm.services.auth import RoleResolver
from crm.services.common import Auditor, Clock, SystemClock
from crm.services.finance_service import FinanceService
from crm.services.ledger import BalanceLedger
from crm.services.order_service import OrderService
from crm.services.sequences import SequenceAllocator
from crm.services.shipment_service import ShipmentService
from crm.storage import Database


@dataclass
class Services:
    orders: OrderService
    shipments: ShipmentService
    finance: FinanceService
    roles: RoleResolver


def build_services(
    db: Database,
    admin_ids: frozenset[int],
    clock: Clock | None = None,
) -> Services:
    clock = clock or SystemClock()
    orders_repo = OrderRepository()
    clients_repo = ClientRepository()
    ledger_repo = LedgerRepository()
    shipments_repo = ShipmentRepository()
    settings_repo = SettingsRepository()

    auditor = Auditor(db, AuditRepository())
    ledger = BalanceLedger(clients_repo, ledger_repo)
    sequences = SequenceAllocator(db, CounterRepository())

    return Services(
        orders=OrderService(db, clock, orders_repo, ledger, sequences, auditor),
        shipments=ShipmentService(db, clock, orders_repo, shipments_repo, sequences, auditor),
        finance=FinanceService(
            db, clock, clients_repo, ledger_repo, settings_repo, ledger, auditor
        ),
        roles=RoleResolver(db, clients_repo, admin_ids),
    )

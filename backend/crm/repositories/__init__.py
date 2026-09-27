from crm.repositories.audit import AuditRepository
from crm.repositories.clients import ClientRepository
from crm.repositories.counters import CounterRepository
from crm.repositories.ledger import LedgerRepository
from crm.repositories.orders import OrderRepository
from crm.repositories.settings import SettingsRepository
from crm.repositories.shipments import ShipmentRepository

__all__ = [
    "AuditRepository",
    "ClientRepository",
    "CounterRepository",
    "LedgerRepository",
    "OrderRepository",
    "SettingsRepository",
    "ShipmentRepository",
]

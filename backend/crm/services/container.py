from dataclasses import dataclass

from crm.repositories import (
    AuditRepository,
    ClientRepository,
    CounterRepository,
    EventReadsRepository,
    EventRepository,
    IntakeRepository,
    LedgerRepository,
    OrderRepository,
    ProfitRepository,
    SettingsRepository,
    ShipmentRepository,
)
from crm.services.auth import RoleResolver
from crm.services.client_service import ClientService
from crm.services.common import Auditor, Clock, SystemClock
from crm.services.events import EventRecorder, EventService
from crm.services.finance_service import FinanceService
from crm.services.group_service import GroupService
from crm.services.image_service import ImageService
from crm.services.intake_service import IntakeService
from crm.services.ledger import BalanceLedger
from crm.services.link_import import LinkImportService
from crm.services.notifications import NotificationService
from crm.services.order_service import OrderService
from crm.services.photo_recognition import PhotoRecognitionService
from crm.services.profit_service import ProfitService
from crm.services.reactions import ReactionService
from crm.services.recognition import Recognizer
from crm.services.security_service import SecurityService
from crm.services.sequences import SequenceAllocator
from crm.services.shipment_service import ShipmentService
from crm.storage import Database
from crm.storage.blobs import BlobStorage


@dataclass
class Services:
    orders: OrderService
    shipments: ShipmentService
    finance: FinanceService
    roles: RoleResolver
    events: EventService
    notifications: NotificationService
    intake: IntakeService
    clients: ClientService
    # None when no file storage is configured (uploads are then refused).
    images: ImageService | None = None
    # None without GEMINI_API_KEY: orders are still accepted, fields stay empty.
    recognizer: Recognizer | None = None
    photo_recognition: PhotoRecognitionService | None = None
    link_import: LinkImportService | None = None
    reactions: ReactionService | None = None
    profit: ProfitService | None = None
    security: SecurityService | None = None
    groups: GroupService | None = None


def build_services(
    db: Database,
    admin_ids: frozenset[int],
    clock: Clock | None = None,
    blob_storage: BlobStorage | None = None,
    recognizer: Recognizer | None = None,
    allowed_chat_ids: frozenset[int] = frozenset(),
) -> Services:
    clock = clock or SystemClock()
    orders_repo = OrderRepository()
    clients_repo = ClientRepository()
    ledger_repo = LedgerRepository()
    shipments_repo = ShipmentRepository()
    settings_repo = SettingsRepository()
    profit_repo = ProfitRepository()

    auditor = Auditor(db, AuditRepository())
    ledger = BalanceLedger(clients_repo, ledger_repo)
    sequences = SequenceAllocator(db, CounterRepository())
    events_repo = EventRepository()
    recorder = EventRecorder(db, events_repo)
    roles = RoleResolver(db, clients_repo, admin_ids)

    return Services(
        orders=OrderService(
            db,
            clock,
            orders_repo,
            ledger,
            sequences,
            auditor,
            recorder,
            event_repo=events_repo,
            intake=IntakeRepository(),
            blobs=blob_storage,
            profit=profit_repo,
        ),
        shipments=ShipmentService(
            db, clock, orders_repo, shipments_repo, sequences, ledger, auditor, recorder
        ),
        finance=FinanceService(
            db, clock, clients_repo, ledger_repo, settings_repo, ledger, auditor, recorder
        ),
        roles=roles,
        events=EventService(db, clock, events_repo, EventReadsRepository()),
        notifications=NotificationService(
            db, clock, events_repo, settings_repo, clients_repo, recorder, auditor, admin_ids
        ),
        clients=ClientService(db, clock, clients_repo, roles, auditor),
        intake=IntakeService(
            db, clock, orders_repo, IntakeRepository(), sequences, auditor, recorder
        ),
        images=ImageService(blob_storage, clock) if blob_storage is not None else None,
        recognizer=recognizer,
        photo_recognition=PhotoRecognitionService(blob_storage, recognizer),
        link_import=LinkImportService(
            ImageService(blob_storage, clock) if blob_storage is not None else None, recognizer
        ),
        reactions=ReactionService(db, clock, orders_repo, recorder),
        profit=ProfitService(db, clock, profit_repo, auditor),
        security=SecurityService(db, clock, auditor),
        groups=GroupService(db, clock, auditor, allowed_chat_ids),
    )

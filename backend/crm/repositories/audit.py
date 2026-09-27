from datetime import datetime
from typing import Any

from crm.storage import Transaction


class AuditRepository:
    """`audit_logs`: append-only. Nothing in the codebase updates or deletes it."""

    collection = "audit_logs"

    def record(
        self,
        tx: Transaction,
        entry_id: str,
        *,
        actor: str,
        source: str,
        action: str,
        entity_type: str,
        entity_id: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        timestamp: datetime,
    ) -> None:
        tx.create(
            self.collection,
            entry_id,
            {
                "actor": actor,
                "source": source,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "before": before,
                "after": after,
                "timestamp": timestamp,
            },
        )

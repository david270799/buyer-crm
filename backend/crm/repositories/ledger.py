from crm.domain.models import Doc, LedgerEntry
from crm.storage import OrderBy, Reader, Transaction


class LedgerRepository:
    """`transactions` collection: append-only history of balance changes."""

    collection = "transactions"

    def get(self, reader: Reader, entry_id: str) -> LedgerEntry | None:
        data = reader.get(self.collection, entry_id)
        return LedgerEntry.from_doc(entry_id, data) if data is not None else None

    def create(self, tx: Transaction, entry_id: str, data: Doc) -> None:
        # `create` (never `set`): an existing entry is never overwritten, which
        # also makes deterministic entry IDs a hard idempotency guard.
        tx.create(self.collection, entry_id, data)

    def list_recent(self, reader: Reader, limit: int = 20) -> list[LedgerEntry]:
        rows = reader.query(
            self.collection, order_by=OrderBy("created_at", descending=True), limit=limit
        )
        return [LedgerEntry.from_doc(doc_id, data) for doc_id, data in rows]

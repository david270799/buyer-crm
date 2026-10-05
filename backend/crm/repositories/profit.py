from crm.domain.models import Doc, ProfitEntry
from crm.storage import Database, OrderBy, Reader, Transaction


class ProfitRepository:
    """`profit_entries`: the admin's extra profit, separate from the client's
    balance history (`transactions`), so no client view can ever list it."""

    collection = "profit_entries"

    def get(self, reader: Reader, entry_id: str) -> ProfitEntry | None:
        data = reader.get(self.collection, entry_id)
        return ProfitEntry.from_doc(entry_id, data) if data is not None else None

    def create(self, tx: Transaction, entry_id: str, data: Doc) -> None:
        tx.create(self.collection, entry_id, data)

    def list_recent(self, reader: Reader, limit: int = 50) -> list[ProfitEntry]:
        rows = reader.query(
            self.collection, order_by=OrderBy("created_at", descending=True), limit=limit
        )
        return [ProfitEntry.from_doc(doc_id, data) for doc_id, data in rows]

    def list_all(self, db: Database) -> list[ProfitEntry]:
        return [ProfitEntry.from_doc(doc_id, data) for doc_id, data in db.scan(self.collection)]

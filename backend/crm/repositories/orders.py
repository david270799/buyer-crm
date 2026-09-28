from collections.abc import Sequence

from crm.domain.models import Doc, Order
from crm.storage import Database, Filter, Reader, Transaction


class OrderRepository:
    collection = "orders"

    def get(self, reader: Reader, order_id: str) -> Order | None:
        data = reader.get(self.collection, order_id)
        return Order.from_doc(order_id, data) if data is not None else None

    def get_many(self, reader: Reader, order_ids: Sequence[str]) -> dict[str, Order | None]:
        docs = reader.get_many(self.collection, order_ids)
        return {
            order_id: Order.from_doc(order_id, data) if data is not None else None
            for order_id, data in docs.items()
        }

    def exists(self, reader: Reader, order_id: str) -> bool:
        return reader.get(self.collection, order_id) is not None

    def create(self, tx: Transaction, order_id: str, data: Doc) -> None:
        tx.create(self.collection, order_id, data)

    def update(self, tx: Transaction, order_id: str, fields: Doc) -> None:
        """Partial update: fields written by other code are left untouched."""
        tx.update(self.collection, order_id, fields)

    def delete(self, tx: Transaction, order_id: str) -> None:
        tx.delete(self.collection, order_id)

    def list_ids(self, reader: Reader) -> list[str]:
        """All order IDs, inside a transaction (the whole collection is read)."""
        return [doc_id for doc_id, _ in reader.query(self.collection)]

    def list_all(self, db: Database) -> list[Order]:
        return [Order.from_doc(doc_id, data) for doc_id, data in db.scan(self.collection)]

    def list_by_shipment(self, reader: Reader, shipment_id: str) -> list[Order]:
        rows = reader.query(self.collection, [Filter("shipment_id", "==", shipment_id)])
        return [Order.from_doc(doc_id, data) for doc_id, data in rows]

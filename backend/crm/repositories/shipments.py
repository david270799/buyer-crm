from crm.domain.models import Doc, Shipment
from crm.storage import Filter, OrderBy, Reader, Transaction


class ShipmentRepository:
    collection = "shipments"

    def get(self, reader: Reader, shipment_id: str) -> Shipment | None:
        data = reader.get(self.collection, shipment_id)
        return Shipment.from_doc(shipment_id, data) if data is not None else None

    def exists(self, reader: Reader, shipment_id: str) -> bool:
        return reader.get(self.collection, shipment_id) is not None

    def find_by_tracking(self, reader: Reader, tracking_code: str) -> list[Shipment]:
        rows = reader.query(self.collection, [Filter("tracking_code", "==", tracking_code)])
        return [Shipment.from_doc(doc_id, data) for doc_id, data in rows]

    def find_by_number(self, reader: Reader, number: int) -> Shipment | None:
        rows = reader.query(self.collection, [Filter("shipment_number", "==", number)], limit=1)
        return Shipment.from_doc(*rows[0]) if rows else None

    def list_recent(self, reader: Reader, limit: int = 20) -> list[Shipment]:
        rows = reader.query(
            self.collection, order_by=OrderBy("shipment_number", descending=True), limit=limit
        )
        return [Shipment.from_doc(doc_id, data) for doc_id, data in rows]

    def max_shipment_number(self, reader: Reader) -> int:
        latest = self.list_recent(reader, limit=1)
        return (latest[0].shipment_number or 0) if latest else 0

    def create(self, tx: Transaction, shipment_id: str, data: Doc) -> None:
        tx.create(self.collection, shipment_id, data)

    def update(self, tx: Transaction, shipment_id: str, fields: Doc) -> None:
        tx.update(self.collection, shipment_id, fields)

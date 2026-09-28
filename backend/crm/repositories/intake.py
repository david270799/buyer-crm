from datetime import datetime

from crm.storage import Reader, Transaction


class IntakeRepository:
    """`intake/tg{chat}_{message}`: which Telegram message became which order.

    Created in the same transaction as the order, with `create`, so the same
    message delivered twice never makes two orders.
    """

    collection = "intake"

    @staticmethod
    def key(chat_id: int, message_id: int) -> str:
        return f"tg{chat_id}_{message_id}"

    def order_id(self, reader: Reader, key: str) -> str | None:
        data = reader.get(self.collection, key)
        value = data.get("order_id") if data else None
        return value if isinstance(value, str) else None

    def create(
        self,
        tx: Transaction,
        key: str,
        *,
        order_id: str,
        chat_id: int,
        message_id: int,
        now: datetime,
    ) -> None:
        tx.create(
            self.collection,
            key,
            {"order_id": order_id, "chat_id": chat_id, "message_id": message_id, "created_at": now},
        )

    def delete(self, tx: Transaction, key: str) -> None:
        tx.delete(self.collection, key)

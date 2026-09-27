from datetime import datetime

from crm.domain.models import ClientInfo
from crm.storage import Reader, Transaction


class ClientRepository:
    collection = "client_info"
    main_client_id = "main_client"

    def get_main(self, reader: Reader) -> ClientInfo | None:
        data = reader.get(self.collection, self.main_client_id)
        return ClientInfo.from_doc(self.main_client_id, data) if data is not None else None

    def set_balance(self, tx: Transaction, balance: int, now: datetime) -> None:
        tx.update(
            self.collection,
            self.main_client_id,
            {"balance": balance, "balance_updated_at": now},
        )

    def set_identity(
        self, tx: Transaction, telegram_id: int, name: str | None, now: datetime, *, create: bool
    ) -> None:
        """Who the client is. Never touches the balance of an existing client."""
        data: dict = {"telegram_id": telegram_id, "name": name, "updated_at": now}
        if create:
            data.update(balance=0, balance_updated_at=now, created_at=now)
        tx.set(self.collection, self.main_client_id, data, merge=True)

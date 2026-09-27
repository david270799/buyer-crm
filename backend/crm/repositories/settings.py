from datetime import datetime
from decimal import Decimal

from crm.domain.models import GeneralSettings
from crm.storage import Reader, Transaction


class SettingsRepository:
    collection = "settings"
    general_id = "general"

    def get_general(self, reader: Reader) -> GeneralSettings:
        return GeneralSettings.from_doc(reader.get(self.collection, self.general_id))

    def set_rate(self, tx: Transaction, rate: Decimal, now: datetime, actor_id: str) -> None:
        # Firestore has no decimal type; the rate is a plain number.
        value: int | float = int(rate) if rate == rate.to_integral_value() else float(rate)
        tx.set(
            self.collection,
            self.general_id,
            {"krw_per_usd": value, "updated_at": now, "updated_by": actor_id},
            merge=True,
        )

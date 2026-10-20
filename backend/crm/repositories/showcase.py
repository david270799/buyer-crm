from crm.domain.models import Doc, ShowcaseItem
from crm.storage import Database, Reader, Transaction


class ShowcaseRepository:
    """`showcase`: product cards; `showcase_likes/tg:{id}`: each viewer's ♥."""

    collection = "showcase"
    likes = "showcase_likes"

    def get(self, reader: Reader, item_id: str) -> ShowcaseItem | None:
        data = reader.get(self.collection, item_id)
        return ShowcaseItem.from_doc(item_id, data) if data is not None else None

    def create(self, tx: Transaction, item_id: str, data: Doc) -> None:
        tx.create(self.collection, item_id, data)

    def update(self, tx: Transaction, item_id: str, data: Doc) -> None:
        tx.update(self.collection, item_id, data)

    def delete(self, tx: Transaction, item_id: str) -> None:
        tx.delete(self.collection, item_id)

    def list_all(self, db: Database) -> list[ShowcaseItem]:
        return [ShowcaseItem.from_doc(i, d) for i, d in db.scan(self.collection)]

    def liked(self, reader: Reader, actor_id: str) -> list[str]:
        data = reader.get(self.likes, actor_id) or {}
        ids = data.get("ids")
        return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []

    def set_liked(self, tx: Transaction, actor_id: str, ids: list[str]) -> None:
        tx.set(self.likes, actor_id, {"ids": ids}, merge=True)

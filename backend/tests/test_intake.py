"""One photo message from Telegram → one new order."""

import threading

import pytest
from conftest import CLIENT_TG, START_BALANCE, audit_actions, balance, seed_order

from crm.domain.enums import Role
from crm.domain.errors import PermissionDeniedError
from crm.domain.views import order_view
from crm.services.common import Actor
from crm.services.image_service import StoredImage
from crm.services.intake_service import IncomingOrder
from crm.services.recognition import Recognition, fallback

pytestmark = pytest.mark.usefixtures("client_doc")

GROUP = -100500
PHOTO = StoredImage("https://cdn.example/p.webp", "https://cdn.example/p_thumb.webp", 1, 1, 1, 1)
LINK = "https://shop.example.kr/item/1"


@pytest.fixture
def client() -> Actor:
    return Actor.telegram(CLIENT_TG, Role.CLIENT)


def incoming(message_id=10, caption=f"42 {LINK}", recognition=None, photo=PHOTO):
    recognition = recognition or Recognition(
        brand="Nike",
        model="Dunk Low 'Panda'",
        category="кроссовки",
        size="42",
        link=LINK,
        confidence=0.93,
        engine="gemini-test",
    )
    return IncomingOrder(GROUP, message_id, caption, photo, recognition)


def test_client_photo_becomes_a_new_order(db, services, client):
    seed_order(db, "n125")

    result = services.intake.accept(client, incoming())

    order = result.order
    assert not result.already_done and order.id == "n126"
    assert order.status.value == "new"
    assert (order.brand, order.model, order.size) == ("Nike", "Dunk Low 'Panda'", "42")
    assert order.source_url == LINK
    assert order.photo_url == PHOTO.photo_url and order.thumbnail_url == PHOTO.thumbnail_url
    assert (order.source_chat_id, order.source_message_id) == (GROUP, 10)
    assert order.client_comment is None  # the caption was only the size and the link
    assert order.charged_amount_krw == 0 and balance(db) == START_BALANCE
    stored = db.get("orders", "n126")
    assert stored["created_by"] == f"tg:{CLIENT_TG}"
    assert stored["recognition"]["engine"] == "gemini-test"
    assert stored["recognition"]["confidence"] == 0.93
    assert "order.intake" in audit_actions(db)


def test_same_message_never_makes_two_orders(db, services, client):
    first = services.intake.accept(client, incoming())
    again = services.intake.accept(client, incoming())
    other = services.intake.accept(client, incoming(message_id=11))

    assert again.already_done and again.order.id == first.order.id
    assert other.order.id != first.order.id
    assert sorted(db.list_ids("orders")) == sorted([first.order.id, other.order.id])


def test_parallel_redelivery_creates_one_order(db, services, client):
    results, errors = [], []
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        try:
            results.append(services.intake.accept(client, incoming()))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert len(db.list_ids("orders")) == 1
    assert len({r.order.id for r in results}) == 1
    assert all(type(e).__name__ == "TransactionContentionError" for e in errors)


def test_without_ai_the_caption_still_fills_size_and_link(db, services, client):
    caption = f"{LINK} 270, срочно"
    result = services.intake.accept(
        client, incoming(caption=caption, recognition=fallback(caption, error="нет ключа"))
    )

    order = result.order
    assert order.brand is None and order.model is None
    assert (order.size, order.source_url) == ("270", LINK)
    assert order.client_comment == "270, срочно"  # the link never goes to the client
    assert db.get("orders", order.id)["recognition"]["error"] == "нет ключа"


def test_invented_link_is_not_stored(db, services, client):
    fake = Recognition(link="https://fake.example/x", engine="g")
    order = services.intake.accept(client, incoming(caption="42", recognition=fake)).order
    assert order.source_url is None


def test_order_without_stored_photo_is_still_created(db, services, client):
    order = services.intake.accept(client, incoming(photo=None)).order
    assert order.photo_url is None and order.brand == "Nike"


def test_recognition_is_admin_only(db, services, client, admin):
    order = services.intake.accept(client, incoming()).order
    assert "recognition" not in order_view(order, Role.CLIENT)
    assert order_view(order, Role.ADMIN)["recognition"]["brand"] == "Nike"


def test_event_is_recorded_for_the_client(db, services, client):
    order = services.intake.accept(client, incoming()).order
    [event] = services.events.for_order(client, order.id)
    assert event.type.value == "order_created" and "42" in (event.body or "")


def test_strangers_cannot_create_orders(db, services):
    with pytest.raises(PermissionDeniedError):
        services.intake.accept(Actor.telegram(555, None), incoming())  # type: ignore[arg-type]


def test_links_never_reach_client_visible_fields(db, services, client):
    sneaky = Recognition(
        brand="Nike https://evil.example/a",
        model="Dunk https://evil.example/b",
        note="см. https://shop.example.kr/item/1",
        engine="g",
        confidence=0.9,
    )
    order = services.intake.accept(client, incoming(recognition=sneaky)).order
    view = order_view(order, Role.CLIENT)
    texts = [view[k] for k in ("brand", "model", "size", "client_comment")]
    assert "http" not in " ".join(str(v) for v in texts) and "source_url" not in view
    assert (order.brand, order.model) == ("Nike", "Dunk")

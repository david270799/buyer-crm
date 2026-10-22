import pytest
from conftest import seed_order

from crm.domain.errors import PermissionDeniedError
from crm.services.order_service import DEFAULT_SHOPS, OrderUpdate

pytestmark = pytest.mark.usefixtures("client_doc")


def test_buy_records_the_shop_and_rebuy_changes_it(db, services, admin):
    seed_order(db, "N5")
    services.orders.buy(admin, "5", 140_000, 170_000, shop="Musinsa")
    order = db.get("orders", "N5")
    assert order["shop"] == "Musinsa" and order["purchases"][0]["shop"] == "Musinsa"

    services.orders.rebuy(admin, "5", 150_000, 170_000, shop="KREAM")
    order = db.get("orders", "N5")
    assert order["shop"] == "KREAM"
    assert [p["shop"] for p in order["purchases"]] == ["Musinsa", "KREAM"]
    # Same purchase again changes nothing.
    assert services.orders.rebuy(admin, "5", 150_000, 170_000, shop="KREAM").already_done


def test_shop_can_be_edited_and_is_searchable(db, services, admin):
    seed_order(db, "N5")
    services.orders.update_details(admin, "5", OrderUpdate(shop="  Coupang "))
    assert db.get("orders", "N5")["shop"] == "Coupang"


def test_shop_list_defaults_and_edits(db, services, admin, client_actor):
    assert services.orders.shop_names(admin) == list(DEFAULT_SHOPS)
    names = services.orders.set_shop_names(admin, ["Naver", " naver ", "Lotte On", ""])
    assert names == ["Naver", "Lotte On"]
    assert services.orders.shop_names(admin) == ["Naver", "Lotte On"]
    with pytest.raises(PermissionDeniedError):
        services.orders.shop_names(client_actor)


def test_client_never_sees_the_shop(db, services, admin):
    from crm.domain.enums import Role
    from crm.domain.views import order_view

    seed_order(db, "N5")
    services.orders.buy(admin, "5", 140_000, 170_000, shop="Musinsa")
    order = services.orders.get_order(admin, "5")
    assert "shop" not in order_view(order, Role.CLIENT)
    assert order_view(order, Role.ADMIN)["shop"] == "Musinsa"


def test_category_from_gemini_words():
    from crm.domain.categories import category_from_text

    assert category_from_text("кроссовки") == "shoes"
    assert category_from_text("Часы") == "watch"
    assert category_from_text("куртка") == "clothes"
    assert category_from_text("рюкзак") == "bag"
    assert category_from_text("что-то") is None
    assert category_from_text(None) is None


def test_category_is_validated_and_visible_to_the_client(db, services, admin):
    from crm.domain.enums import Role
    from crm.domain.errors import ValidationError
    from crm.domain.views import order_view

    seed_order(db, "N5")
    services.orders.update_details(admin, "5", OrderUpdate(category="watch"))
    order = services.orders.get_order(admin, "5")
    assert order_view(order, Role.CLIENT)["category"] == "watch"
    with pytest.raises(ValidationError):
        services.orders.update_details(admin, "5", OrderUpdate(category="car"))

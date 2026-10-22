from datetime import timedelta

import pytest
from conftest import seed_order

from crm.domain.enums import OrderStatus
from crm.services.order_service import OrderQuery

pytestmark = pytest.mark.usefixtures("client_doc")


def test_bought_order_is_stuck_after_four_days(db, services, admin, clock):
    seed_order(db, "N1")
    seed_order(db, "N2")
    services.orders.buy(admin, "1", 100, 200, shop="Musinsa")
    services.orders.buy(admin, "2", 100, 200)
    services.orders.set_status(admin, ["N2"], OrderStatus.WAREHOUSE)

    clock.current += timedelta(days=3, hours=23)
    assert services.orders.stuck_days(services.orders.get_order(admin, "1")) is None

    clock.current += timedelta(hours=2)
    assert services.orders.stuck_days(services.orders.get_order(admin, "1")) == 4
    assert services.orders.stuck_days(services.orders.get_order(admin, "2")) is None  # at warehouse
    page = services.orders.list_orders(admin, OrderQuery(stuck=True))
    assert [o.id for o in page.items] == ["N1"]
    assert services.orders.overview(admin).stuck_count == 1


def test_client_does_not_get_stuck_filter_or_count(db, services, admin, client_actor, clock):
    seed_order(db, "N1")
    services.orders.buy(admin, "1", 100, 200)
    clock.current += timedelta(days=5)
    assert services.orders.overview(client_actor).stuck_count is None
    page = services.orders.list_orders(client_actor, OrderQuery(stuck=True))
    assert page.total == 1  # the filter is ignored for the client


def test_problem_filter_joins_attention_and_stuck(db, services, admin, client_actor, clock):
    seed_order(db, "N1")
    seed_order(db, "N2", attention_required=True)
    seed_order(db, "N3", attention_required=True)
    seed_order(db, "N4")
    services.orders.buy(admin, "1", 100, 200)  # will be stuck
    services.orders.buy(admin, "3", 100, 200)  # stuck and «внимание»: counted once
    clock.current += timedelta(days=5)

    page = services.orders.list_orders(admin, OrderQuery(problem=True, sort="oldest"))
    assert [o.id for o in page.items] == ["N1", "N2", "N3"]
    assert services.orders.overview(admin).problem_count == 3
    # The client sees only «внимание» and gets no count.
    page = services.orders.list_orders(client_actor, OrderQuery(problem=True, sort="oldest"))
    assert [o.id for o in page.items] == ["N2", "N3"]
    assert services.orders.overview(client_actor).problem_count is None

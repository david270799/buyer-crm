import pytest

from crm.domain.errors import PermissionDeniedError


def test_setgroup_adds_and_removes_groups(services, admin):
    assert services.groups.listing(admin) == {}
    services.groups.add(admin, -100123, "Заказы")
    assert services.groups.allowed_ids() == frozenset({-100123})
    assert services.groups.listing(admin) == {-100123: "Заказы"}
    services.groups.remove(admin, -100123)
    assert services.groups.allowed_ids() == frozenset()


def test_only_admin_changes_groups(services, client_actor):
    with pytest.raises(PermissionDeniedError):
        services.groups.add(client_actor, -1, "x")

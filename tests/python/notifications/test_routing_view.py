
from __future__ import annotations

import pytest

from src.core.notifications import routing_view as rv


class _View:
    revision = 3
    paused = False

    def destinations(self):
        return [rv.DestinationView(id="d_aaaaaaaaaaaa", kind="slack", name="n", enabled=True, scope="global", config={})]

    def is_ticked(self, column, type_id):
        return True


class _Writer:
    async def disable_locally(self, dest_id, reason):
        return None


@pytest.fixture(autouse=True)
def _clean():
    rv.uninstall_routing()
    yield
    rv.uninstall_routing()


def test_empty_defaults():
    assert rv.current_view() is None
    assert rv.routing_writer() is None
    assert dict(rv.current_statuses()) == {}


def test_install_and_read():
    w = _Writer()
    rv.install_routing(lambda: _View(), w)
    view = rv.current_view()
    assert isinstance(view, rv.RoutingView)
    assert view.destinations()[0].projects == ()
    assert rv.routing_writer() is w
    st = {"d_aaaaaaaaaaaa": rv.DestinationStatus(consecutive_permanent_failures=2)}
    rv.install_status_provider(lambda: st)
    assert rv.current_statuses()["d_aaaaaaaaaaaa"].consecutive_permanent_failures == 2


def test_quiet_hours_frozen():
    q = rv.QuietHours("22:00", "07:00")
    with pytest.raises(Exception):
        q.start = "x"  # type: ignore[misc]

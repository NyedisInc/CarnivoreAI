from __future__ import annotations

import pytest

from src.core.stats.batch_store import BatchStore
from src.core.stats.store import StatsStore
from src.core.stats.store_port import StatsStoreLike
from tests.python.attention.test_manager_port_drift import _assigned_on_self, _own_members, _params


def test_the_real_store_has_every_port_member_with_its_parameters():
    attrs, methods = _own_members(StatsStoreLike)
    assert attrs and methods, "the port declares nothing: the test would pass on nothing"
    assigned = _assigned_on_self(StatsStore)
    for name in attrs:
        assert hasattr(StatsStore, name) or name in assigned, f"StatsStore lost attribute {name}"
    for name in methods:
        impl = getattr(StatsStore, name, None)
        assert impl is not None, f"StatsStore lost method {name}"
        missing = _params(getattr(StatsStoreLike, name)) - _params(impl)
        assert not missing, f"StatsStore.{name} lost parameters {sorted(missing)}"


@pytest.mark.parametrize("member", ["state_dir", "db_path", "connect", "connect_read", "discard_read", "revision"])
def test_the_batch_view_answers_every_port_member(member):
    store = StatsStore.__new__(StatsStore)
    store.state_dir, store.db_path = "s", "d"
    assert hasattr(BatchStore(store), member)

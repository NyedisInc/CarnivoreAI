
from __future__ import annotations

import pytest

import src.config  # noqa: F401
from src.core.automations import models as m
from src.core.automations import targets
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for
from tests.python.perf_conn_reuse.helpers import count_connects, opens_of

N = 40
CARD = {"kind": "swarm_card", "project_id": 1, "title": "t", "summary": "s"}


async def _noop(ctx, automation, run):
    return m.RunOutcome()


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setitem(targets.RUNNERS, "swarm_card", _noop)
    return AutomationStore(storage_for(tmp_path), clock=lambda: 1_800_000_000.0, notify=lambda _t: None)


def test_list_and_latest_runs_reuse_a_connection_and_see_each_create(store, monkeypatch):
    store.create(name="first", cron="0 7 * * 1", target=CARD)
    store.list_all()
    opened = count_connects(monkeypatch)
    for i in range(N):
        store.create(name=f"auto{i}", cron="0 7 * * 1", target=CARD)
        assert len(store.list_all()) == i + 2
        store.latest_stopped_runs()
    reads = opens_of(opened, "automations.db")
    print(f"\nautomations: {2 * N} reads + {N} creates, {reads} connects in total (reads before: {2 * N})")
    assert reads == N

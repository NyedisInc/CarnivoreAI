
from __future__ import annotations

import asyncio
from contextlib import closing
from types import SimpleNamespace

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.api import peer_auth, scheduled_tasks_routes
from src.core import scheduled_tasks
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_hosts, peer_links, peer_scheduled_tasks
from src.core.federation.peer_client import PeerUnreachable
from src.models.scheduled_tasks import ScheduledTask, ScheduledTasksList

TASK = {"id": "nightly", "name": "nightly", "file_state": "ok"}


class Client:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    async def request(self, method, path, *, json=None, timeout=None):
        self.calls.append((method, path))
        if self.error:
            raise self.error
        body = {"state": "ok", "tasks": [TASK], "total": 1}
        return SimpleNamespace(status_code=200, json=lambda: body)


class Links:
    def __init__(self, clients):
        self._clients = clients

    def client(self, iid):
        return self._clients.get(iid)


@pytest.fixture()
def world(tmp_path, monkeypatch):
    ensure_db_migrated(tmp_path)
    path = db_path_for(tmp_path)
    monkeypatch.setattr(peer_auth, "open_db", lambda: connect(path, create=False))
    with closing(connect(path, create=False)) as conn:
        up = peer_hosts.upsert(conn, install_id="iid-up", label="hosta", grant_id="g", fid="f", initiator=True)
        down = peer_hosts.upsert(conn, install_id="iid-down", label="lab", grant_id="g2", fid="f2", initiator=True)
    local = ScheduledTasksList(state="ok", tasks=[ScheduledTask(id="mine", name="mine", file_state="ok")], total=1)
    return SimpleNamespace(up=up, down=down, local=local, mp=monkeypatch)


def merged(world, clients):
    return asyncio.run(peer_scheduled_tasks.merge(world.local, peer_auth.open_db, Links(clients)))


def test_a_peer_task_is_listed_under_its_host_and_a_down_peer_is_named(world):
    client = Client()
    out = merged(world, {"iid-up": client})
    assert client.calls == [("GET", "/scheduled-tasks")]
    by_id = {(t.id, t.host_key): t for t in out.tasks}
    assert ("mine", None) in by_id and by_id[("nightly", world.up.key)].host_label == "hosta"
    assert {p.host_key: p.state for p in out.peers} == {world.up.key: "ok", world.down.key: "peer_unavailable"}
    out = merged(world, {"iid-up": Client(PeerUnreachable("peer offline")), "iid-down": None})
    assert [t.id for t in out.tasks] == ["mine"] and {p.state for p in out.peers} == {"peer_unavailable"}


def test_a_peer_caller_gets_only_this_macs_list(world):
    world.mp.setattr(scheduled_tasks.READER, "read", lambda: world.local)
    client = Client()
    world.mp.setattr(peer_links, "LINKS", Links({"iid-up": client}))
    peer = peer_auth.Principal("peer", None)
    out = asyncio.run(scheduled_tasks_routes.list_scheduled_tasks(peer))
    assert client.calls == [] and out.peers == [] and [t.id for t in out.tasks] == ["mine"]
    owner = asyncio.run(scheduled_tasks_routes.list_scheduled_tasks(peer_auth.OWNER))
    assert client.calls and len(owner.tasks) == 2

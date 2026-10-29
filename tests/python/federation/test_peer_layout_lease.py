
from __future__ import annotations

import asyncio
from contextlib import closing
from types import SimpleNamespace

import pytest

from tests.layouts_helpers import add_sessions, grid, row

# ruff: noqa: E402
from src.api import session_lease_routes
from src.core.layouts import store as store
from src.core.auto_sleep import sleeper
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_hosts, peer_layout_lease, shadow_rows
from src.core.federation.peer_client import PeerUnreachable
from src.core.layouts.lease import SESSION_LEASES

IID = "iid-studio"
OWNER_UUID = "11111111-2222-4333-8444-555555555555"


class Client:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    async def request(self, method, path, *, json=None, timeout=None):
        self.calls.append((method, path))
        if self.error:
            raise self.error
        return SimpleNamespace(status_code=200)


class Links:
    def __init__(self, client):
        self._client = client

    def client(self, _iid):
        return self._client


@pytest.fixture()
def world(tmp_path):
    ensure_db_migrated(tmp_path)
    path = db_path_for(tmp_path)
    (local_id, _), = add_sessions(path, 1)
    with closing(connect(path, create=False)) as conn:
        peer_hosts.upsert(conn, install_id=IID, label="studio", grant_id="g", fid="f", initiator=True)
        key = peer_hosts.host_key_for(IID)
        shadow = shadow_rows.sync_peer(conn, host_key=key, peer_install_id=IID, complete=True, rows=[{
            "session_uuid": OWNER_UUID, "row_id": 7, "name": "carnivore_far", "working_dir": "/far/dir",
            "label": "far", "agent_type": "claude", "agent_family": "claude", "agent_family_source": "launch"}])
        made = store.create_layout(conn, "mix", grid(row(local_id), row(shadow["carnivore_far"].session_id)))
    return path, key, made.layout.layout_uuid, shadow["carnivore_far"].session_id


def _run(world, links):
    path, key, layout, _ = world
    return asyncio.run(peer_layout_lease.forward_lease(
        layout, lambda: connect(path, create=False), links))


def test_a_peer_member_gets_a_lease_sent_to_its_owner(world):
    client = Client()
    result = _run(world, Links(client))
    assert client.calls == [("PUT", "/sessions/carnivore_far/active")]
    assert result == {f"remote:{world[1]}:carnivore_far": "ok"}


def test_a_down_peer_is_named_and_never_raises(world):
    assert _run(world, Links(None)) == {f"remote:{world[1]}:carnivore_far": "peer_unreachable"}
    assert _run(world, Links(Client(PeerUnreachable("peer offline")))) == {f"remote:{world[1]}:carnivore_far": "peer_unreachable"}


def test_the_owner_holds_a_leased_session_awake(tmp_path, monkeypatch):
    ensure_db_migrated(tmp_path)
    path = db_path_for(tmp_path)
    (rid, uuid), = add_sessions(path, 1)
    monkeypatch.setattr(type(session_lease_routes.settings), "get_state_dir", lambda self: tmp_path)
    assert sleeper.leased_member_rows(path) == set()
    name = _tmux_name(path, rid)
    asyncio.run(session_lease_routes.renew_session_lease(name))
    try:
        assert sleeper.leased_member_rows(path) == {rid}
    finally:
        SESSION_LEASES.release(uuid)


def test_an_unknown_name_is_404(tmp_path, monkeypatch):
    ensure_db_migrated(tmp_path)
    monkeypatch.setattr(type(session_lease_routes.settings), "get_state_dir", lambda self: tmp_path)
    with pytest.raises(session_lease_routes.HTTPException) as caught:
        asyncio.run(session_lease_routes.renew_session_lease("nope"))
    assert caught.value.status_code == 404


def _tmux_name(path, rid):
    with closing(connect(path, create=False)) as conn:
        return conn.execute("SELECT tmux_name FROM sessions WHERE id = ?", (rid,)).fetchone()[0]

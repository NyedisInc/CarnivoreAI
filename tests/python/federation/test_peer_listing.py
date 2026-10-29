
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from datetime import datetime

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core.db import connect, db_path_for, get_meta
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import META_INSTALL_ID
from src.core.federation import peer_hosts, peer_listing, peer_serve, shadow_rows
from src.core.federation.peer_link import CONNECTED, DISCONNECTED
from src.core.hosts.identity import remote_session_id
from src.models import Session, SessionInfo, SessionStatus


class Reply:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


class Mac:

    def __init__(self, tmp_path, name):
        self.name, self.dir = name, tmp_path / name
        self.dir.mkdir()
        ensure_db_migrated(self.dir)
        with closing(self.open_db()) as conn:
            self.install_id = get_meta(conn, META_INSTALL_ID)
        self.own = []
        self.leak = []
        self.other = None
        self.state = CONNECTED

    def open_db(self):
        return connect(db_path_for(self.dir), create=False)

    def add_session(self, tmux_name, status="working"):
        with closing(self.open_db()) as conn:
            rid = add_row(conn, uuid=f"{self.name}-uuid-{tmux_name}", name=tmux_name, epoch=1000 + len(self.own),
                          origin="created", socket="carnivore")
            conn.execute("UPDATE sessions SET working_dir = '/work/" + self.name + "' WHERE id = ?", (rid,))
        self.own.append(SessionInfo(
            session=Session(id=f"ses_{self.name}_{tmux_name}", working_dir=f"/work/{self.name}", status=SessionStatus.RUNNING,
                            created_at=datetime(2026, 9, 29)),
            tmux_session=tmux_name, session_row_id=rid, activity_status=status, unread=True, startup_gate="ready"))

    def pair(self, other):
        self.other = other
        with closing(self.open_db()) as conn:
            peer_hosts.upsert(conn, install_id=other.install_id, label=other.name, grant_id="g", fid="f", initiator=True)

    def client(self, _peer_id):
        return _Client(self.other) if self.state == CONNECTED else None

    async def list_body(self, *, as_peer):
        return await peer_listing.for_caller(self.own + self.leak, is_peer=as_peer, open_db=self.open_db, links=_Links(self))


class _Links:
    def __init__(self, mac):
        self.mac = mac

    def client(self, peer_id):
        return self.mac.client(peer_id)

    def state(self, peer_id):
        return self.mac.state


class _Client:
    def __init__(self, other):
        self.other = other

    async def request(self, method, path, **_kw):
        served = await self.other.list_body(as_peer=True)
        return Reply(json.loads(json.dumps([i.model_dump(mode="json") for i in served])))


@pytest.fixture
def macs(tmp_path):
    peer_listing.reset()
    a, b = Mac(tmp_path, "A"), Mac(tmp_path, "B")
    a.pair(b)
    b.pair(a)
    a.add_session("alpha")
    b.add_session("bravo")
    return a, b


def _names(rows):
    return sorted(str(r.tmux_session) for r in rows)


def test_each_mac_lists_both_machines_sessions_exactly_once(macs):
    a, b = macs

    async def run():
        for _ in range(2):
            rows_a, rows_b = await a.list_body(as_peer=False), await b.list_body(as_peer=False)
        return rows_a, rows_b

    rows_a, rows_b = asyncio.run(run())
    assert _names(rows_a) == ["alpha", "bravo"] and _names(rows_b) == ["alpha", "bravo"]
    shown = next(r for r in rows_a if r.tmux_session == "bravo")
    assert shown.session.id == remote_session_id(peer_hosts.host_key_for(b.install_id), "bravo")
    assert shown.host_key == peer_hosts.host_key_for(b.install_id) and shown.host_state == "up"
    assert shown.activity_status == "working" and shown.unread is True and shown.startup_gate == "ready"
    assert shown.origin_install_id == b.install_id and shown.session.pty_pid is None
    assert next(r for r in rows_a if r.tmux_session == "alpha").origin_install_id is None


def test_a_shadow_row_and_a_peer_project_exist_and_the_uuid_is_uuid5(macs):
    a, b = macs
    asyncio.run(a.list_body(as_peer=False))
    with closing(a.open_db()) as conn:
        row = conn.execute("SELECT session_uuid, origin, host_key, project_id, lifecycle FROM sessions "
                           "WHERE origin = 'peer'").fetchone()
        root = conn.execute("SELECT root FROM projects WHERE id = ?", (row["project_id"],)).fetchone()[0]
        link = conn.execute("SELECT peer_session_uuid, peer_name FROM peer_sessions").fetchone()
    assert row["host_key"] == peer_hosts.host_key_for(b.install_id) and row["lifecycle"] == "running"
    assert root == f"peer://{row['host_key']}/work/B"
    assert row["session_uuid"] == shadow_rows.shadow_uuid(b.install_id, link["peer_session_uuid"])
    assert link["peer_name"] == "bravo"


def test_the_uuid5_and_the_row_survive_a_restart_of_either_mac(macs):
    a, b = macs
    first = asyncio.run(a.list_body(as_peer=False))
    before = next(r for r in first if r.tmux_session == "bravo")
    peer_listing.reset()
    again = asyncio.run(a.list_body(as_peer=False))
    after = next(r for r in again if r.tmux_session == "bravo")
    assert (after.session_uuid, after.session_row_id) == (before.session_uuid, before.session_row_id)
    with closing(a.open_db()) as conn:
        conn.execute("DELETE FROM peer_sessions")
        conn.execute("DELETE FROM sessions WHERE origin = 'peer'")
    peer_listing.reset()
    rebuilt = next(r for r in asyncio.run(a.list_body(as_peer=False)) if r.tmux_session == "bravo")
    assert rebuilt.session_uuid == before.session_uuid
    assert shadow_rows.shadow_uuid(b.install_id, "x") == shadow_rows.shadow_uuid(b.install_id, "x")
    assert shadow_rows.shadow_uuid(b.install_id, "x") != shadow_rows.shadow_uuid(a.install_id, "x")


def _dirty(mac):
    imported = asyncio.run(mac.list_body(as_peer=False))
    mac.leak = [r for r in imported if r.host_key != "local"]
    mac.leak.append(SessionInfo(session=Session(id="remote:studio-ssh:ssh1", working_dir="/x", status=SessionStatus.RUNNING),
                                tmux_session="ssh1", host_key="studio-ssh"))


def test_a_mac_never_reexports_imported_rows_and_the_two_import_guards_each_hold(macs, monkeypatch):
    a, b = macs
    asyncio.run(b.list_body(as_peer=False))
    asyncio.run(a.list_body(as_peer=False))
    _dirty(b)

    def alphas(rows):
        return [r for r in rows if r.tmux_session == "alpha"]

    peer_listing.reset()
    assert len(alphas(asyncio.run(a.list_body(as_peer=False)))) == 1

    def stamp_all(infos, open_db):
        return [i.model_copy(update={"origin_install_id": i.origin_install_id or b.install_id}) for i in infos]

    with monkeypatch.context() as m:
        m.setattr(peer_serve, "owned_rows", lambda infos: list(infos))
        peer_listing.reset()
        assert len(alphas(asyncio.run(a.list_body(as_peer=False)))) == 1
    with monkeypatch.context() as m:
        m.setattr(peer_listing, "accept", lambda raw, iid: isinstance(raw, dict))
        peer_listing.reset()
        assert len(alphas(asyncio.run(a.list_body(as_peer=False)))) == 1
    with monkeypatch.context() as m:
        m.setattr(peer_serve, "owned_rows", lambda infos: list(infos))
        m.setattr(peer_serve, "serve_to_peer", stamp_all)
        m.setattr(peer_listing, "accept", lambda raw, iid: isinstance(raw, dict))
        peer_listing.reset()
        rows = asyncio.run(a.list_body(as_peer=False))
        assert len(alphas(rows)) == 2
    assert "ssh1" not in _names(asyncio.run(a.list_body(as_peer=False)))


def test_a_down_link_keeps_the_rows_disconnected_and_never_idle(macs):
    a, b = macs
    asyncio.run(a.list_body(as_peer=False))
    a.state = DISCONNECTED
    rows = asyncio.run(a.list_body(as_peer=False))
    bravo = next(r for r in rows if r.tmux_session == "bravo")
    assert bravo.host_state == "disconnected" and bravo.activity_status == "unknown" and bravo.status_source == "none"
    peer_listing.reset()
    cold = next(r for r in asyncio.run(a.list_body(as_peer=False)) if r.tmux_session == "bravo")
    assert cold.host_state == "disconnected" and cold.activity_status == "unknown"
    with closing(a.open_db()) as conn:
        assert conn.execute("SELECT lifecycle FROM sessions WHERE origin = 'peer'").fetchone()[0] == "running"


def test_only_a_complete_answer_stops_a_shadow_row(macs):
    a, b = macs
    asyncio.run(a.list_body(as_peer=False))
    b.own = []
    b.state, a.state = DISCONNECTED, DISCONNECTED
    asyncio.run(a.list_body(as_peer=False))
    with closing(a.open_db()) as conn:
        assert conn.execute("SELECT lifecycle FROM sessions WHERE origin = 'peer'").fetchone()[0] == "running"
    a.state = CONNECTED
    peer_listing.reset()
    assert _names(asyncio.run(a.list_body(as_peer=False))) == ["alpha"]
    with closing(a.open_db()) as conn:
        assert conn.execute("SELECT lifecycle FROM sessions WHERE origin = 'peer'").fetchone()[0] == "stopped"


def test_a_session_moved_to_the_peer_shows_despite_the_stopped_row_it_left_behind(macs):
    a, b = macs
    with closing(a.open_db()) as conn:
        add_row(conn, uuid="B-uuid-bravo", name="bravo", epoch=1, lifecycle="stopped", origin="adopted", socket="carnivore")
    assert "bravo" in _names(asyncio.run(a.list_body(as_peer=False)))

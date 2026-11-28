
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from typing import Any, Dict, Optional

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401
from tests.python.federation.test_peer_asleep_rows import _insert_swarm_agent, _sleep
from tests.python.federation.test_peer_listing import Mac, Reply

# ruff: noqa: E402
from src.core.computers import direction
from src.core.federation import peer_forward, peer_hosts, peer_listing, peer_serve, shadow_rows
from src.core.federation.peer_link import CONNECTED, DISCONNECTED
from src.core.hosts.identity import remote_session_id

UID_SHARED = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


class _StarLinks:

    def __init__(self, peers: Dict[str, tuple["Mac", str]], *, include_swarm: bool = False) -> None:
        self._peers = peers
        self._include_swarm = include_swarm

    def client(self, peer_id: str) -> Optional["_StarClient"]:
        entry = self._peers.get(peer_id)
        if entry is None or entry[1] != CONNECTED:
            return None
        mac, _state = entry
        return _StarClient(mac, caller_id=self._owner_id, links_for_hub=self._hub_links.get(peer_id), include_swarm=self._include_swarm)

    def state(self, peer_id: str) -> str:
        entry = self._peers.get(peer_id)
        return entry[1] if entry is not None else DISCONNECTED

    def bind(self, owner_id: str, hub_links: Optional[Dict[str, "_StarLinks"]] = None) -> "_StarLinks":
        self._owner_id = owner_id
        self._hub_links = hub_links or {}
        return self


class _StarClient:

    def __init__(
        self,
        target: Mac,
        *,
        caller_id: str,
        links_for_hub: Optional[_StarLinks] = None,
        include_swarm: bool = False,
    ) -> None:
        self.target = target
        self.caller_id = caller_id
        self.links_for_hub = links_for_hub
        self.include_swarm = include_swarm

    async def request(self, method: str, path: str, **_kw: Any) -> Reply:
        if path == "/sessions/asleep":
            body: Any = await asyncio.to_thread(
                peer_serve.serve_asleep_to_peer,
                self.target.open_db,
                include_swarm=self.include_swarm,
                caller_install_id=self.caller_id,
            )
        elif path == "/sessions/list-and-asleep":
            owned = await peer_listing.for_caller(
                self.target.own,
                is_peer=True,
                open_db=self.target.open_db,
                include_swarm=self.include_swarm,
                caller_install_id=self.caller_id,
            )
            asleep = await asyncio.to_thread(
                peer_serve.serve_asleep_to_peer,
                self.target.open_db,
                include_swarm=self.include_swarm,
                caller_install_id=self.caller_id,
            )
            relayed = await asyncio.to_thread(
                peer_listing.relayed_for_peer,
                self.target.open_db,
                self.links_for_hub,
                caller_install_id=self.caller_id,
                include_swarm=self.include_swarm,
            )
            body = {
                "list": [i.model_dump(mode="json") for i in owned],
                "asleep": asleep,
                "relayed": [i.model_dump(mode="json") for i in relayed],
            }
        else:
            owned = await peer_listing.for_caller(
                self.target.own,
                is_peer=True,
                open_db=self.target.open_db,
                include_swarm=self.include_swarm,
                caller_install_id=self.caller_id,
            )
            body = [i.model_dump(mode="json") for i in owned]
        return Reply(json.loads(json.dumps(body)))


def _add_project(conn: Any, *, root: str, name: str, uid: str, host_key: str = "local") -> int:
    now = "2026-11-26T00:00:00Z"
    return int(
        conn.execute(
            "INSERT INTO projects (root, raw_path, display_name, source, presence, host_key, "
            "created_at, updated_at, last_opened_at, uid) VALUES (?, ?, ?, 'user', 'present', ?, ?, ?, ?, ?)",
            (root, root, name, host_key, now, now, now, uid),
        ).lastrowid
    )


def _mark_one_way_in_db(mac: Mac, target_install_id: str) -> None:
    with closing(mac.open_db()) as conn:
        conn.execute(
            "INSERT INTO computer_links (peer_install_id, role, transport, inbound_control, updated_at) "
            "VALUES (?, 'peer', 'ssh', 0, '2026-11-26T00:00:00Z') "
            "ON CONFLICT(peer_install_id) DO UPDATE SET inbound_control = 0",
            (target_install_id,),
        )
        conn.commit()


@pytest.fixture(autouse=True)
def _clean_state() -> Any:
    peer_listing.reset()
    with direction._TOWARD_LOCK:
        direction._ONE_WAY_TOWARD.clear()
    yield
    peer_listing.reset()
    with direction._TOWARD_LOCK:
        direction._ONE_WAY_TOWARD.clear()


def test_swarm_sessions_visible_in_peer_listing_and_respect_containment(tmp_path: Any) -> None:
    a, b = Mac(tmp_path, "A"), Mac(tmp_path, "B")
    a.pair(b)
    b.pair(a)
    b.add_session("regular_live")
    b.add_session("leader_live")
    b.add_session("worker_live")
    _sleep(b, "regular_sleep")
    _sleep(b, "leader_sleep")

    with closing(b.open_db()) as conn:
        ids = {r[0]: int(r[1]) for r in conn.execute("SELECT tmux_name, id FROM sessions")}
        _insert_swarm_agent(conn, slug="lead-1", rank="project", session_row_id=ids["leader_live"])
        _insert_swarm_agent(conn, slug="work-1", rank="feature", session_row_id=ids["worker_live"])
        _insert_swarm_agent(conn, slug="lead-sleep", rank="company", session_row_id=ids["leader_sleep"])
        conn.commit()

    b.own = [
        row.model_copy(update={"swarm_agent_id": 77, "swarm_rank": "project"})
        if row.tmux_session == "leader_live"
        else row
        for row in b.own
    ]

    default_live = {i.tmux_session for i in peer_serve.serve_to_peer(b.own, b.open_db)}
    assert default_live == {"regular_live"}
    default_asleep = {r["tmux_session"] for r in peer_serve.serve_asleep_to_peer(b.open_db)}
    assert default_asleep == {"regular_sleep"}

    served_live = {
        i.tmux_session: i
        for i in peer_serve.serve_to_peer(b.own, b.open_db, include_swarm=True, caller_install_id=a.install_id)
    }
    assert set(served_live) == {"regular_live", "leader_live", "worker_live"}
    assert served_live["regular_live"].is_swarm is False
    assert served_live["regular_live"].swarm_role is None
    assert served_live["leader_live"].is_swarm is True
    assert served_live["leader_live"].swarm_role == "project"
    assert served_live["leader_live"].swarm_rank == "project"
    assert served_live["leader_live"].swarm_agent_id is None
    assert served_live["worker_live"].is_swarm is True
    assert served_live["worker_live"].swarm_role == "feature"
    assert served_live["worker_live"].swarm_agent_id is None

    served_asleep = {
        r["tmux_session"]: r
        for r in peer_serve.serve_asleep_to_peer(b.open_db, include_swarm=True, caller_install_id=a.install_id)
    }
    assert set(served_asleep) == {"regular_sleep", "leader_sleep"}
    assert served_asleep["regular_sleep"]["is_swarm"] is False
    assert served_asleep["leader_sleep"]["is_swarm"] is True
    assert served_asleep["leader_sleep"]["swarm_role"] == "company"

    _mark_one_way_in_db(b, a.install_id)
    assert peer_serve.serve_to_peer(b.own, b.open_db, include_swarm=True, caller_install_id=a.install_id) == []
    assert peer_serve.serve_asleep_to_peer(b.open_db, include_swarm=True, caller_install_id=a.install_id) == []


def test_two_hop_read_only_relay_visibility_and_invariants(tmp_path: Any) -> None:
    a, b, c = Mac(tmp_path, "A"), Mac(tmp_path, "B"), Mac(tmp_path, "C")
    a.pair(b)
    b.pair(a)
    a.pair(c)
    c.pair(a)

    a.add_session("alpha")
    b.add_session("bravo")
    c.add_session("charlie")

    with closing(c.open_db()) as conn:
        c_pid = _add_project(conn, root="/work/C", name="Shared Proj", uid=UID_SHARED)
        conn.execute("UPDATE sessions SET project_id = ? WHERE tmux_name = 'charlie'", (c_pid,))
        conn.commit()
    c.own[0] = c.own[0].model_copy(update={"project_id": c_pid})
    with closing(b.open_db()) as conn:
        b_stub_pid = _add_project(
            conn,
            root=f"peer://{c.install_id}/{UID_SHARED}",
            name="Shared Proj",
            uid=UID_SHARED,
            host_key=peer_hosts.host_key_for(c.install_id),
        )
        conn.commit()

    links_a = _StarLinks({b.install_id: (b, CONNECTED), c.install_id: (c, CONNECTED)}).bind(a.install_id)
    links_b = _StarLinks({a.install_id: (a, CONNECTED)}).bind(b.install_id, {a.install_id: links_a})
    links_c = _StarLinks({a.install_id: (a, CONNECTED)}).bind(c.install_id, {a.install_id: links_a})

    rows_a = asyncio.run(peer_listing.for_caller(a.own, is_peer=False, open_db=a.open_db, links=links_a))
    assert sorted(r.tmux_session for r in rows_a) == ["alpha", "bravo", "charlie"]

    rows_b = asyncio.run(peer_listing.for_caller(b.own, is_peer=False, open_db=b.open_db, links=links_b))
    by_name_b = {r.tmux_session: r for r in rows_b}
    assert sorted(by_name_b) == ["alpha", "bravo", "charlie"]

    charlie_on_b = by_name_b["charlie"]
    assert charlie_on_b.hop == 1
    assert charlie_on_b.origin_install_id == c.install_id
    assert charlie_on_b.origin_label == "C"
    assert charlie_on_b.host_key == peer_hosts.host_key_for(c.install_id)
    assert charlie_on_b.session.id == remote_session_id(peer_hosts.host_key_for(c.install_id), "charlie")
    assert charlie_on_b.session.pty_pid is None
    assert charlie_on_b.session_uuid == shadow_rows.shadow_uuid(c.install_id, "C-uuid-charlie")
    assert charlie_on_b.project_id == b_stub_pid
    assert charlie_on_b.project_name == "Shared Proj"
    assert charlie_on_b.session_row_id is None

    with closing(b.open_db()) as conn:
        assert peer_forward.resolve(conn, charlie_on_b.session.id) is None
        assert peer_forward.resolve(conn, charlie_on_b.session_uuid) is None

    re_relayed = peer_serve.serve_relayed_to_peer(
        {c.install_id: [charlie_on_b]},
        b.open_db,
        caller_install_id="iid-d",
    )
    assert re_relayed == []

    relayed_to_c = peer_listing.relayed_for_peer(a.open_db, links_a, caller_install_id=c.install_id)
    assert [r.tmux_session for r in relayed_to_c] == ["bravo"]
    peer_listing._SNAPSHOTS.pop(a.install_id, None)
    peer_listing._RELAYED_SNAPSHOTS.pop(a.install_id, None)
    rows_c = asyncio.run(peer_listing.for_caller(c.own, is_peer=False, open_db=c.open_db, links=links_c))
    assert sorted(r.tmux_session for r in rows_c) == ["alpha", "bravo", "charlie"]
    assert sum(1 for r in rows_c if r.tmux_session == "charlie") == 1

    with closing(b.open_db()) as conn:
        hub_row = peer_hosts.get(conn, a.install_id, include_mesh=True)
    assert hub_row is not None
    forged = [
        {
            "origin_install_id": b.install_id,
            "origin_label": "B",
            "hop": 1,
            "tmux_session": "bravo_echo",
            "session_uuid": "B-uuid-bravo",
            "session": {"id": "ses_B_bravo", "working_dir": "/work/B", "status": "running"},
        }
    ]
    assert asyncio.run(peer_listing.ingest_relayed(hub_row, b.open_db, forged)) is True
    assert peer_listing._RELAYED_SNAPSHOTS.get(a.install_id) == {}

    peer_listing.reset()
    asyncio.run(peer_listing.for_caller(a.own, is_peer=False, open_db=a.open_db, links=links_a))
    assert "charlie" in {r.tmux_session for r in asyncio.run(peer_listing.for_caller(b.own, is_peer=False, open_db=b.open_db, links=links_b))}

    direction.note_restrictions(c.install_id, [direction.RESTRICTION_ONE_WAY])
    assert peer_listing.relayed_for_peer(a.open_db, links_a, caller_install_id=b.install_id) == []
    peer_listing._SNAPSHOTS.pop(a.install_id, None)
    rows_b_one_way = asyncio.run(peer_listing.for_caller(b.own, is_peer=False, open_db=b.open_db, links=links_b))
    assert "charlie" not in {r.tmux_session for r in rows_b_one_way}
    direction.note_restrictions(c.install_id, [])

    peer_listing._SNAPSHOTS.pop(a.install_id, None)
    assert "charlie" in {r.tmux_session for r in asyncio.run(peer_listing.for_caller(b.own, is_peer=False, open_db=b.open_db, links=links_b))}
    links_a._peers[c.install_id] = (c, DISCONNECTED)
    peer_listing._SNAPSHOTS.pop(a.install_id, None)
    rows_b_disc = asyncio.run(peer_listing.for_caller(b.own, is_peer=False, open_db=b.open_db, links=links_b))
    assert "charlie" not in {r.tmux_session for r in rows_b_disc}
    links_a._peers[c.install_id] = (c, CONNECTED)

    peer_listing._SNAPSHOTS.pop(a.install_id, None)
    b.pair(c)
    c.pair(b)
    links_b_direct = _StarLinks({a.install_id: (a, CONNECTED), c.install_id: (c, CONNECTED)}).bind(
        b.install_id, {a.install_id: links_a}
    )
    rows_b_direct = asyncio.run(peer_listing.for_caller(b.own, is_peer=False, open_db=b.open_db, links=links_b_direct))
    charlies = [r for r in rows_b_direct if r.tmux_session == "charlie"]
    assert len(charlies) == 1
    assert charlies[0].hop == 0
    assert charlies[0].session_row_id is not None

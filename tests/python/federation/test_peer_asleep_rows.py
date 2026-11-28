
from __future__ import annotations

import asyncio
import json
from contextlib import closing

from tests.python.federation.test_peer_listing import Mac, Reply, _Links, macs  # noqa: F401

# ruff: noqa: E402
from src.api.session_record_payload import _session_record_payload, attach_host_labels
from src.core import session_sleep, session_store
from src.core.federation import peer_listing, peer_serve


def _sleep(mac, tmux_name):
    from tests.lifecycle_helpers import add_row

    with closing(mac.open_db()) as conn:
        rid = add_row(conn, uuid=f"{mac.name}-uuid-{tmux_name}", name=tmux_name, epoch=2000, origin="created", socket="carnivore")
        conn.execute("UPDATE sessions SET working_dir = ?, lifecycle = 'stopped', lifecycle_source = ?, title = ? WHERE id = ?",
                     (f"/work/{mac.name}", session_sleep.LIFECYCLE_SOURCE_SLEPT_BY_TIMER, "Kestrel", rid))


def _asleep_records(mac):
    with closing(mac.open_db()) as conn:
        rows = session_store.list_sessions(conn, lifecycle="stopped", include_archived=False)
        rows = [r for r in rows if session_sleep.is_asleep(r)]
        attach_host_labels(conn, rows)
    return [_session_record_payload(r) for r in rows]


def test_a_peers_asleep_agent_is_listed_here_as_that_computers_asleep_row(macs, monkeypatch):
    a, b = macs
    _sleep(b, "carnivore_kestrel")

    class Client:
        def __init__(self, other):
            self.other = other

        async def request(self, method, path, **_kw):
            if path == "/sessions/asleep":
                body = await asyncio.to_thread(peer_serve.serve_asleep_to_peer, self.other.open_db)
            else:
                body = [i.model_dump(mode="json") for i in await self.other.list_body(as_peer=True)]
            return Reply(json.loads(json.dumps(body)))

    monkeypatch.setattr(type(a), "client", lambda self, _id: Client(self.other))
    asyncio.run(a.list_body(as_peer=False))
    records = [r for r in _asleep_records(a) if r.host_key not in (None, "local")]
    assert [(r.tmux_name, r.asleep, r.title, r.host_label) for r in records] == [("carnivore_kestrel", True, "Kestrel", "B")]
    assert records[0].host_key.startswith("peer-")
    assert peer_serve.serve_asleep_to_peer(a.open_db) == []


def test_the_asleep_route_serves_slim_peer_rows_without_a_500(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import session_sleep_routes
    from src.api.peer_auth import require_peer_sessions
    from src.core.federation import peer_serve

    slim = [{"origin_install_id": "studio-install", "session_uuid": "u-1", "tmux_session": "carnivore_X", "label": "X",
             "working_dir": "/w", "agent_type": "claude", "agent_family": "claude", "agent_family_source": "launched",
             "source": "slept_by_timer"}]
    monkeypatch.setattr(peer_serve, "serve_asleep_to_peer", lambda open_db: slim)
    app = FastAPI()
    app.include_router(session_sleep_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_peer_sessions] = lambda: None

    @app.middleware("http")
    async def as_peer(request, call_next):
        request.state.peer_grant = object()
        return await call_next(request)

    reply = TestClient(app).get("/api/v1/sessions/asleep")
    assert reply.status_code == 200
    assert reply.json() == slim


def _insert_swarm_agent(conn, *, slug, rank, session_row_id=None, parked_row_id=None, torn_down_at=None):
    now = "2026-11-24T00:00:00Z"
    conn.execute(
        "INSERT INTO swarm_agents (slug, rank, display_name, job, repo_dir, memory_scope, effort, character_seed, "
        "color_slot, thread_key, session_row_id, parked_row_id, state, torn_down_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, '/work/B', 'project', 'medium', 1, 1, ?, ?, ?, ?, ?, ?, ?)",
        (slug, rank, slug, f"job for {slug}", f"agent:{slug}", session_row_id, parked_row_id,
         "torn_down" if torn_down_at else "asleep", torn_down_at, now, now),
    )


def test_active_swarm_agents_excluded_from_peer_listings_and_stale_shadows_cleaned(macs, monkeypatch):
    a, b = macs
    b.add_session("live_leader")
    b.add_session("torn_live")
    b.add_session("remote_body")
    for name in ("regular_sleep", "swarm_feature_sleep", "swarm_leader_sleep", "parked_sleep", "torn_sleep"):
        _sleep(b, name)

    with closing(b.open_db()) as conn:
        ids = {r[0]: int(r[1]) for r in conn.execute("SELECT tmux_name, id FROM sessions")}
        pass

    class Client:
        def __init__(self, other):
            self.other = other

        async def request(self, method, path, **_kw):
            if path == "/sessions/asleep":
                body = await asyncio.to_thread(peer_serve.serve_asleep_to_peer, self.other.open_db)
            else:
                body = [i.model_dump(mode="json") for i in await self.other.list_body(as_peer=True)]
            return Reply(json.loads(json.dumps(body)))

    monkeypatch.setattr(type(a), "client", lambda self, _id: Client(self.other))

    asyncio.run(a.list_body(as_peer=False))
    asleep_before = {r.tmux_name for r in _asleep_records(a) if r.host_key not in (None, "local")}
    assert {"swarm_feature_sleep", "swarm_leader_sleep", "regular_sleep", "parked_sleep", "torn_sleep"} <= asleep_before

    with closing(b.open_db()) as conn:
        _insert_swarm_agent(conn, slug="live-leader", rank="project", session_row_id=ids["live_leader"])
        _insert_swarm_agent(conn, slug="torn-live", rank="feature", session_row_id=ids["torn_live"], torn_down_at="2026-11-19T00:00:00Z")
        _insert_swarm_agent(conn, slug="feat-sleep", rank="feature", session_row_id=ids["swarm_feature_sleep"])
        _insert_swarm_agent(conn, slug="lead-sleep", rank="project", session_row_id=ids["swarm_leader_sleep"])
        _insert_swarm_agent(conn, slug="parked-left", rank="feature", session_row_id=None, parked_row_id=ids["parked_sleep"])
        _insert_swarm_agent(conn, slug="torn-sleep", rank="feature", session_row_id=ids["torn_sleep"], torn_down_at="2026-11-19T00:00:00Z")
        conn.execute(
            "INSERT INTO swarm_remote_bodies (session_row_id, home_install_id, home_agent_id, project_uid, rank, slug, mirror_dir, created_at) "
            "VALUES (?, 'home-iid', 99, 'proj-uid', 'task', 'remote-slug', '/work/B', '2026-11-24T00:00:00Z')",
            (ids["remote_body"],),
        )
        conn.commit()

    served_live = {i.tmux_session for i in peer_serve.serve_to_peer(b.own, b.open_db)}
    assert served_live == {"bravo", "torn_live", "remote_body"}
    served_asleep = {r["tmux_session"] for r in peer_serve.serve_asleep_to_peer(b.open_db)}
    assert served_asleep == {"regular_sleep", "parked_sleep", "torn_sleep"}

    peer_listing.reset()
    live_after = asyncio.run(a.list_body(as_peer=False))
    remote_live_after = {i.tmux_session for i in live_after if i.host_key != "local"}
    assert remote_live_after == {"bravo", "torn_live", "remote_body"}
    asleep_after = {r.tmux_name for r in _asleep_records(a) if r.host_key not in (None, "local")}
    assert asleep_after == {"regular_sleep", "parked_sleep", "torn_sleep"}

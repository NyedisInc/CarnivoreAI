
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


from __future__ import annotations

import asyncio
import json
import os
import tempfile
from contextlib import closing
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_msess_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_msess_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

from datetime import datetime  # noqa: E402

from tests.lifecycle_helpers import add_row  # noqa: E402
from src.api import federation_mesh_routes, peer_auth, peer_route_guard, session_crud_routes  # noqa: E402
from src.core import session_change_notice  # noqa: E402
from src.core.computers import mesh  # noqa: E402
from src.core.db import connect, db_path_for, set_meta  # noqa: E402
from src.core.db_models import META_INSTALL_ID  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.event_hub import EventHub  # noqa: E402
from src.core.federation import (mesh_listener, mesh_peers, mesh_powers, peer_event_stream, peer_forward, peer_hosts,  # noqa: E402
                                 peer_links, peer_listing, peer_token)
from src.core.federation.peer_link import CONNECTED  # noqa: E402
from src.core.pack.machines import capabilities  # noqa: E402
from src.main import app  # noqa: E402
from src.core.relay_identity.device_key import b64url  # noqa: E402
from src.models import Session, SessionInfo, SessionStatus  # noqa: E402
from tests.python.computers.test_mesh_links import A, B, C, _pair, _wait, root  # noqa: E402,F401,F811
from tests.python.pack import test_settings_signing as ss  # noqa: E402

RULE = peer_forward.Rule("GET", "/sessions/restart/preview", peer_forward.FORWARD, ("query", "session_name", peer_forward.NAME))


class Probe:

    def __init__(self, inner) -> None:
        self.inner, self.seen, self.routes = inner, [], inner.routes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            self.seen.append(scope)
        await self.inner(scope, receive, send)


def _row(name: str, row_id: int, host_key: str = "local", sid: str = "") -> SessionInfo:
    return SessionInfo(session=Session(id=sid or f"ses_c_{name}", working_dir="/work/c", status=SessionStatus.RUNNING, created_at=datetime(2026, 9, 29)),
                       tmux_session=name, session_row_id=row_id, activity_status="working", unread=False, startup_gate="ready", host_key=host_key)


def test_the_mesh_challenge_prefix_is_its_own():
    grant = SimpleNamespace(grant_id="g", public_key=ss.PUB[B])
    ts, nonce = 1_790_000_000, b"n" * 16
    for prefix, other in ((peer_token.CHALLENGE_PREFIX, peer_token.MESH_CHALLENGE_PREFIX), (peer_token.MESH_CHALLENGE_PREFIX, peer_token.CHALLENGE_PREFIX)):
        sig = ss.KEYS["b"].sign(peer_token.challenge_message("g", C, ts, nonce, prefix=prefix))
        args = (grant, C, ts, b64url(nonce), sig)
        peer_token.verify_challenge(*args, now=ts, nonces=peer_token.NonceCache(), prefix=prefix)
        with pytest.raises(peer_token.PeerTokenError):
            peer_token.verify_challenge(*args, now=ts, nonces=peer_token.NonceCache(), prefix=other)
    assert peer_token.challenge_message("g", C, ts, nonce) == peer_token.CHALLENGE_PREFIX + b"g\x00" + C.encode() + b"\x00" + ts.to_bytes(8, "big") + nonce


def test_a_member_lists_follows_and_controls_a_member_and_forgets_it_when_removed(monkeypatch, tmp_path, root):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(mesh, "FETCH_DEBOUNCE", 0.0)
    monkeypatch.setattr(mesh_powers, "OPEN_POWERS", frozenset({mesh_powers.MESH_LINK, mesh_powers.MESH_SESSIONS}))
    c_dir, b_dir = tmp_path / "c_state", tmp_path / "b_state"
    for folder in (c_dir, b_dir):
        folder.mkdir()
        ensure_db_migrated(folder)
    c_path, b_path = db_path_for(c_dir), db_path_for(b_dir)
    with closing(connect(c_path, create=False)) as conn:
        set_meta(conn, META_INSTALL_ID, C)
        ids = {name: add_row(conn, uuid=f"c-uuid-{name}", name=name, epoch=1000 + n, origin="created", socket="carnivore")
               for n, name in enumerate(("alpha", "beta", "leak"))}
    monkeypatch.setattr(peer_auth, "open_db", lambda: connect(c_path, create=False))
    monkeypatch.setattr(peer_auth, "read_install_id", lambda conn: C)
    monkeypatch.setattr(federation_mesh_routes, "_WINDOWS", federation_mesh_routes.pairing.KeyedWindows(60, 60.0))

    def b_open():
        return connect(b_path, create=False)

    c_rows = [_row("alpha", ids["alpha"]), _row("beta", ids["beta"]), _row("leak", ids["leak"], host_key="peer-x", sid="remote:peer-x:imp")]

    async def owner_listing(_state):
        return list(c_rows)

    monkeypatch.setattr(session_crud_routes, "build_owner_listing", owner_listing)
    c_hub, b_hub = EventHub(), EventHub()
    monkeypatch.setattr(app.state, "event_hub", c_hub, raising=False)
    b_state = SimpleNamespace(event_hub=b_hub)
    links_b = peer_links.PeerLinks(open_db=b_open, listener_path="unused")
    monkeypatch.setattr(peer_links, "LINKS", links_b)
    peer_listing.reset()
    holder: dict = {}
    reg_b = mesh_peers.MeshPeers(open_db=b_open, self_iid=B, fed_dir=root / "b", sign=ss.KEYS["b"].sign,
                                 trusted=lambda peer: holder["b"].trusted(peer), ensure=lambda *a, **k: holder["b"].ensure(*a, **k),
                                 touch=lambda iid: holder["b"].touch(iid))

    async def scenario() -> None:
        probe = Probe(app)
        hooks = {"b": {"on_session": reg_b.session_changed, "on_list": reg_b.list_changed, "bind": lambda links: holder.update(b=links)}}
        async with _pair(root, tmp_path, attach=("c",), hooks=hooks) as p:
            monkeypatch.setattr(mesh_peers, "REGISTRY", reg_b)
            await mesh_listener.start(probe)
            try:
                await _wait(lambda: C in p.links["b"]._sessions and B in p.links["c"]._sessions)
                await _wait(lambda: reg_b.state(C) == CONNECTED)
                with closing(b_open()) as conn:
                    mesh_row = peer_hosts.get(conn, C, include_mesh=True)
                assert mesh_row is not None and mesh_row.back_kind == "mesh" and mesh_row.initiator is False
                rows = await peer_listing.peer_rows(b_open, links_b, force=True)
                wire = sorted(r.session.id for r in rows)
                assert wire == [f"remote:{mesh_row.key}:alpha", f"remote:{mesh_row.key}:beta"], wire
                assert {r.host_key for r in rows} == {mesh_row.key}
                with closing(b_open()) as conn:
                    assert conn.execute("SELECT COUNT(*) FROM peer_sessions WHERE host_key = ?", (mesh_row.key,)).fetchone()[0] == 2
                client = mesh_peers.session_client(links_b, C)
                assert client is not None
                served = await client.request("GET", "/sessions/list")
                assert served.status_code == 200
                ids = [r["session"]["id"] for r in served.json()]
                assert ids and not any(i.startswith("remote:") for i in ids), ids
                refused = await client.request("GET", "/sessions?session_id=remote:peer-x:abc")
                assert refused.status_code == 409 and "not_local" in refused.body.decode()
                listener = b_hub.register()
                peer_event_stream.sync(b_state, b_open)
                try:
                    await _wait(lambda: mesh_row.key in peer_event_stream.LIVE)
                    seen = None
                    for _ in range(100):
                        c_hub.publish(session_change_notice.build_status_notice(session_id="ses_c_alpha", tmux_session="alpha", epoch=1,
                                                                              activity_status="working"))
                        try:
                            frame = json.loads(await asyncio.wait_for(listener.stream.get(), 0.2))
                        except asyncio.TimeoutError:
                            continue
                        if frame.get("session_id") == f"remote:{mesh_row.key}:alpha":
                            seen = frame
                            break
                    assert seen is not None and seen.get("origin") == "peer"
                finally:
                    await peer_event_stream.stop()
                before = len(probe.seen)
                reply = await peer_route_guard.forward_reply(RULE, mesh_row, "/sessions/restart/preview?session_name=alpha", None)
                assert reply.status_code not in (401, 403, 502, 503, 504), reply.status_code
                hit = [s for s in probe.seen[before:] if s["path"].endswith("/sessions/restart/preview")]
                assert hit and all(s["mesh_peer"] == B for s in hit)
                with closing(b_open()) as conn:
                    assert C not in [r.peer_install_id for r in peer_hosts.list_peers(conn)]
                    assert C in [r.peer_install_id for r in peer_hosts.list_peers(conn, include_mesh=True)]
                assert C not in [r.peer_install_id for r in peer_listing.read_peers(b_open)]
                assert C in [r.peer_install_id for r in peer_listing.read_peers(b_open, True)]
                assert links_b.connected_clients() == [] and [i for i, _ in mesh_peers.session_clients(links_b)] == [C]
                monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
                with closing(b_open()) as conn:
                    assert peer_hosts.list_peers(conn, include_mesh=True) == []
                assert peer_listing.read_peers(b_open, True) == []
                monkeypatch.setattr(mesh_peers, "REGISTRY", None)
                assert mesh_peers.session_client(links_b, C) is None and mesh_peers.session_client(None, C) is None
                assert mesh_peers.session_state(links_b, C) == "disconnected" and mesh_peers.session_minor(links_b, C) == 0
                assert mesh_peers.session_clients(links_b) == [] and mesh_peers.session_clients(None) == []
                monkeypatch.setattr(mesh_peers, "REGISTRY", reg_b)
                monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
                sb = p.links["b"]._sessions[C]
                assert sb.extra.get("grant_id")
                assert p.alpha.refresh_roster(_inputs(p), ).startswith("bump:")
                assert p.pack["b"].custody.merge_roster_v2(p.alpha.custody.roster_v2_wire(), A)
                await p.links["b"].list_changed()
                await _wait(lambda: C not in p.links["b"]._sessions)
                with closing(b_open()) as conn:
                    assert peer_hosts.get(conn, C, include_mesh=True) is None
                    assert conn.execute("SELECT COUNT(*) FROM peer_sessions WHERE host_key = ?", (mesh_row.key,)).fetchone()[0] == 0
                assert mesh_peers.session_client(links_b, C) is None and not reg_b.holds(C)
                assert await peer_listing.peer_rows(b_open, links_b, force=True) == []
            finally:
                await reg_b.stop()
                await mesh_listener.stop()

    def _inputs(p):
        from tests.python.computers.test_mesh_links import _inputs as make

        return make(p.idents, p.ports, only=("a", "b"))

    try:
        asyncio.run(scenario())
    finally:
        peer_event_stream.LIVE.clear()
        peer_listing.reset()

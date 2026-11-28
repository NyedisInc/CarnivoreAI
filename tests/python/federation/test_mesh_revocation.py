
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import os
import tempfile
import time
from contextlib import closing
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mrev_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mrev_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

from websockets.exceptions import WebSocketException  # noqa: E402

from tests.lifecycle_helpers import add_row  # noqa: E402
from src.api import federation_mesh_routes, peer_auth, peer_route_guard, session_crud_routes, session_notes_routes  # noqa: E402
from src.core.computers import mesh, mesh_choice  # noqa: E402
from src.core.computers.member_listener import MemberListener, Rendezvous  # noqa: E402
from src.core.computers.mux import frames as mf  # noqa: E402
from src.core.db import connect, db_path_for, set_meta  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.db_models import META_INSTALL_ID  # noqa: E402
from src.core.event_hub import EventHub  # noqa: E402
from src.core.federation import (mesh_grants, mesh_listener, mesh_peers, mesh_powers, peer_client, peer_forward, peer_hosts,  # noqa: E402
                                 peer_links, peer_listing, peer_sockets, peer_terminal_proxy, peer_token)
from src.core.federation import mesh_client  # noqa: E402
from src.core.federation.mesh_client import MeshPeerClient, MeshTransport  # noqa: E402
from src.core.federation.peer_link import CONNECTED, DISCONNECTED  # noqa: E402
from src.core.pack.machines import capabilities, roster_doc, roster_v2, settings_sign  # noqa: E402
from src.core.relay_identity.device_key import DeviceKey, b64url  # noqa: E402
from src.main import app  # noqa: E402
from tests.python.computers.test_mesh_links import A, B, C, _identity_in, _inputs, _pair, _wait, root  # noqa: E402,F401,F811
from tests.python.pack import test_settings_signing as ss  # noqa: E402

EVENTS = "/ws/events?listing=push"
NOTE_RULE = peer_forward.RULES[("PUT", "/sessions/{session_name}/note")]


class _World(SimpleNamespace):
    pass


def _world(monkeypatch, tmp_path, root) -> _World:
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(mesh, "FETCH_DEBOUNCE", 0.0)
    monkeypatch.setattr(mesh_powers, "OPEN_POWERS", frozenset(mesh_powers.OPEN_POWERS | {mesh_powers.MESH_SESSIONS}))
    c_dir, b_dir = tmp_path / "c_state", tmp_path / "b_state"
    for folder in (c_dir, b_dir):
        folder.mkdir()
        ensure_db_migrated(folder)
    c_path, b_path = db_path_for(c_dir), db_path_for(b_dir)
    with closing(connect(c_path, create=False)) as conn:
        set_meta(conn, META_INSTALL_ID, C)
        add_row(conn, uuid="c-uuid-alpha", name="alpha", epoch=1000, origin="created", socket="carnivore")
    monkeypatch.setattr(peer_auth, "open_db", lambda: connect(c_path, create=False))
    monkeypatch.setattr(peer_auth, "read_install_id", lambda conn: C)
    monkeypatch.setattr(federation_mesh_routes, "_WINDOWS", federation_mesh_routes.pairing.KeyedWindows(60, 600.0))
    monkeypatch.setattr(app.state, "event_hub", EventHub(), raising=False)

    async def owner_listing(_state):
        return []

    monkeypatch.setattr(session_crud_routes, "build_owner_listing", owner_listing)

    def b_open():
        return connect(b_path, create=False)

    links_b = peer_links.PeerLinks(open_db=b_open, listener_path="unused")
    monkeypatch.setattr(peer_links, "LINKS", links_b)
    peer_listing.reset()
    holder: dict = {}
    reg_b = mesh_peers.MeshPeers(open_db=b_open, self_iid=B, fed_dir=root / "b", sign=ss.KEYS["b"].sign,
                                 trusted=lambda peer: holder["b"].trusted(peer), ensure=lambda *a, **k: holder["b"].ensure(*a, **k),
                                 touch=lambda iid: holder["b"].touch(iid))
    hooks = {"on_session": reg_b.session_changed, "on_list": reg_b.list_changed, "bind": lambda links: holder.update(b=links)}
    return _World(b_open=b_open, c_path=c_path, links_b=links_b, reg_b=reg_b, holder=holder, hooks=hooks)


@contextlib.asynccontextmanager
async def _serving(monkeypatch, tmp_path, root, w: _World, **pair_args):
    hooks = {"b": w.hooks, **pair_args.pop("hooks", {})}
    async with _pair(root, tmp_path, hooks=hooks, **pair_args) as p:
        monkeypatch.setattr(mesh_peers, "REGISTRY", w.reg_b)
        await mesh_listener.start(app)
        try:
            yield p
        finally:
            await w.reg_b.stop()
            await mesh_listener.stop()
            peer_listing.reset()


async def _linked(p, w: _World) -> None:
    await _wait(lambda: C in p.links["b"]._sessions and B in p.links["c"]._sessions)
    await _wait(lambda: w.reg_b.state(C) == CONNECTED)


async def _open_events(w: _World, p):
    client = w.reg_b.client(C)
    assert client is not None
    token = await client.bearer()
    ws = await peer_terminal_proxy.connect_upstream(client, EVENTS)
    gid = p.links["c"]._sessions[B].extra["grant_id"]
    await _wait(lambda: peer_sockets.count(gid) == 1)
    return ws, gid, token


async def _raw(session, token, path="/sessions/list", method="GET", dir_=None):
    transport = MeshTransport(session, B, dir_)
    try:
        route = await transport.establish()
        client = MeshPeerClient(route, session=session, self_iid=B, sign=ss.KEYS["b"].sign, trusted=lambda _p: None)
        return (await client._send(method, peer_client._url(path), token, None)).status_code
    finally:
        await transport.close()


async def _gone(ws, gid) -> None:
    await _wait(lambda: peer_sockets.count(gid) == 0, 2.0)
    await asyncio.wait_for(ws.wait_closed(), 2.0)
    assert ws.close_code in (4412, 1006, 1000, 1001, 1011), ws.close_code


def _merge(p, names, inputs, **kw) -> None:
    assert p.alpha.refresh_roster(inputs, **kw).startswith("bump:")
    for name in names:
        assert p.pack[name].custody.merge_roster_v2(p.alpha.custody.roster_v2_wire(), A)


async def _changed(p, *names) -> None:
    for name in names:
        await p.links[name].list_changed()


@pytest.mark.parametrize("case", ["removed", "link_switch_off", "one_way", "rotated_replace", "mesh_off"])
def test_revocation_closes_open_sockets_and_refuses_at_once(case, monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            await _linked(p, w)
            ws, gid, old_token = await _open_events(w, p)
            sb = p.links["b"]._sessions[C]
            extra = []
            try:
                if case in ("removed", "link_switch_off"):
                    if case == "removed":
                        _merge(p, ("b", "c"), _inputs(p.idents, p.ports, only=("a", "c")))
                    else:
                        _merge(p, ("b", "c"), _inputs(p.idents, p.ports), link_peers={B: False})
                    await _changed(p, "c", "b")
                    await _gone(ws, gid)
                    assert await mesh_grants.current(B) is None and mesh.trusted_pin(B) is None
                    await _wait(lambda: mesh_peers.session_client(w.links_b, C) is None, 3.0)
                    if case == "removed":
                        await _wait(lambda: not w.reg_b.holds(C), 3.0)
                        with closing(w.b_open()) as conn:
                            assert peer_hosts.get(conn, C, include_mesh=True) is None
                elif case == "one_way":
                    inputs = [dataclasses.replace(i, one_way=True) if i.install_id == B else i for i in _inputs(p.idents, p.ports)]
                    _merge(p, ("b", "c"), inputs)
                    await _changed(p, "c", "b")
                    await _wait(lambda: w.reg_b._entries.get(C) is not None and w.reg_b._entries[C].link is None, 3.0)
                    sess = p.links["b"]._sessions[C]
                    assert not sess.mux.closed.is_set()
                    await _gone(ws, gid)
                    assert await _raw(sess, old_token, dir_=root / "b") == 403
                    transport = MeshTransport(sess, B, root / "b")
                    try:
                        client = MeshPeerClient(await transport.establish(), session=sess, self_iid=B, sign=ss.KEYS["b"].sign,
                                                trusted=lambda _p: p.links["b"]._lst)
                        fresh_token = await client.bearer(force=True)
                        reply = await client._send("GET", peer_client._url("/sessions/list"), fresh_token, None)
                        assert reply.status_code == 403 and b"computer_one_way" in reply.body
                        try:
                            again = await peer_terminal_proxy._open(client, EVENTS, fresh_token)
                        except (WebSocketException, OSError) as exc:
                            assert "403" in str(exc) or "4401" in str(exc) or "rejected" in str(exc).lower(), exc
                        else:
                            await asyncio.wait_for(again.wait_closed(), 2.0)
                            assert again.close_code in (4401, 4403), again.close_code
                    finally:
                        await transport.close()
                    started = time.monotonic()
                    assert await mesh_peers.connect(w.links_b, C) is None
                    assert time.monotonic() - started < 0.5
                elif case == "rotated_replace":
                    monkeypatch.setattr(mesh, "DUP_WINDOW_SECONDS", 0.0)
                    fresh = _identity_in(root, "b2", ss.KEYS["b"], B)
                    _merge(p, ("b", "c"), _inputs(p.idents, p.ports, next_certs={"b": fresh.cert.der}))
                    await _changed(p, "c", "b")
                    await asyncio.sleep(0.3)
                    assert peer_sockets.count(gid) == 1 and not ws.close_code
                    await p.links["b"]._dialer.stop()
                    listener2 = MemberListener(identity=fresh, rendezvous=Rendezvous(), host="127.0.0.1")
                    assert await listener2.bind(0)
                    await listener2.set_pins([p.idents["a"].cert], [p.idents["c"].cert])
                    extra.append(listener2)
                    await p.listeners["c"].set_pins([p.idents["a"].cert], [p.idents["b"].cert, fresh.cert])
                    links2 = mesh.MeshLinks(identity=fresh, iid=B, listener=listener2, custody=lambda: p.pack["b"].custody,
                                            after_change=lambda: asyncio.sleep(0), star_linked=lambda _i: 0.0, backoff=lambda _a: 0, stagger=0.0,
                                            jitter=0.0)
                    links2.start()
                    extra.append(links2)
                    await links2.list_changed()
                    assert await links2.ensure(C, 8.0)
                    await _gone(ws, gid)
                    assert p.links["c"]._sessions[B].extra["grant_id"] != gid
                    assert await _raw(links2._sessions[C], old_token, dir_=root / "b") == 401
                else:
                    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
                    assert await _raw(sb, old_token, dir_=root / "b") == 401
                    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
                    assert peer_sockets.count(gid) == 1
                    await mesh.detach()
                    await _gone(ws, gid)
                    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
            finally:
                for thing in reversed(extra):
                    await (thing.stop() if hasattr(thing, "stop") else asyncio.sleep(0))
                await ws.close()

    asyncio.run(scenario())


def test_takeover_hold_closes_sockets_refuses_and_ends_the_session_at_expiry(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    D = "install-d"
    monkeypatch.setitem(ss.IDS, "d", D)
    monkeypatch.setitem(ss.LABELS, "d", "fourth")
    monkeypatch.setitem(ss.KEYS, "d", DeviceKey.from_seed(bytes([4]) * 32))
    monkeypatch.setitem(ss.PUB, D, b64url(ss.KEYS["d"].raw_pub))
    now = [1000.0]

    def adopt_claim(taker, claimant) -> None:
        roster, rsig = roster_doc.from_wire(claimant.custody.roster_wire())
        assert taker.custody.adopt_alpha(claimant.custody.settings(), settings_sign.signature_from(claimant.custody.state.settings_signature()),
                                         roster, rsig, settings_sign.CLAIM, C)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, only=("a", "b", "c", "d"), meshers=("b", "c", "d"),
                            clocks={"c": lambda: now[0]}) as p:
            L, pack = p.links, p.pack
            monkeypatch.setattr(mesh, "_ACTIVE", L["c"])
            try:
                await _wait(lambda: C in L["b"]._sessions and B in L["c"]._sessions and w.reg_b.state(C) == CONNECTED)
                held = pack["b"].custody.held_lists()[0]
                await w.reg_b.list_changed(None, True)
                assert w.reg_b.state(C) == DISCONNECTED
                started = time.monotonic()
                assert await w.reg_b.connect(C) is None and time.monotonic() - started < 1.0
                await w.reg_b.list_changed(held, False)
                await _wait(lambda: w.reg_b.state(C) == CONNECTED, 5.0)
                ws, gid, old_token = await _open_events(w, p)
                sbc = L["b"]._sessions[C]
                assert p.alpha.refresh_roster(_inputs(p.idents, p.ports, ("a", "b", "c", "d")), eligible={D: True}).startswith("bump:")
                for name in ("b", "c", "d"):
                    for peer, post, caps in pack[name]._connected():
                        if peer != A:
                            await pack[name].beat(peer, post, caps)
                pack["d"].custody.takeover_on = lambda: True
                assert pack["d"].custody.claim()
                L["c"]._schedule_fetch = lambda *a, **k: None
                adopt_claim(pack["c"], pack["d"])
                await L["c"].list_changed()
                assert L["c"]._grace_until is not None
                await _gone(ws, gid)
                assert await _raw(sbc, old_token, dir_=root / "b") == 401
                assert not sbc.mux.closed.is_set()
                now[0] += mesh.TAKEOVER_GRACE_SECONDS + 1
                await L["c"].list_changed()
                await asyncio.wait_for(sbc.mux.closed.wait(), 5)
                assert sbc.mux.goaway_reason == mf.GO_REMOVED
                await _wait(lambda: not w.reg_b.holds(C) or w.reg_b._entries[C].session is not sbc, 5.0)
            finally:
                monkeypatch.setattr(mesh, "_ACTIVE", None)

    asyncio.run(scenario())


def test_on_demand_dial_drives_a_member_end_to_end_and_unreachable_is_refused_in_words(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    monkeypatch.setattr(mesh_choice, "STANDING_LINKS", 0)
    monkeypatch.setattr(session_notes_routes, "_db_path", lambda: w.c_path)

    async def release(p) -> None:
        monkeypatch.setattr(mesh, "ON_DEMAND_IDLE_SECONDS", 0.0)
        await p.links["b"]._sweep()
        await _wait(lambda: C not in p.links["b"]._sessions, 5.0)
        await _wait(lambda: w.reg_b.state(C) == DISCONNECTED or not w.reg_b.holds(C), 5.0)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            await asyncio.sleep(0.5)
            assert not p.links["b"]._sessions
            client = await w.reg_b.connect(C)
            assert client is not None
            with closing(w.b_open()) as conn:
                assert peer_hosts.get(conn, C, include_mesh=True).back_kind == "mesh"
            sess = p.links["b"]._sessions[C]
            transport = MeshTransport(sess, B, root / "b")
            try:
                bare = MeshPeerClient(await transport.establish(), session=sess, self_iid=B, sign=ss.KEYS["b"].sign, trusted=lambda _p: None)
                gid = p.links["c"]._sessions[B].extra["grant_id"]
                ts, nonce = int(time.time()), os.urandom(16)
                sig = ss.KEYS["b"].sign(peer_token.challenge_message(gid, C, ts, nonce, prefix=peer_token.CHALLENGE_PREFIX))
                reply = await bare._send("POST", mesh_client.TOKEN_PATH, None, {"ts": ts, "nonce": b64url(nonce), "signature": sig})
                assert reply.status_code == 401 and b"grant_invalid" in reply.body
                token = await client.bearer()
                control = {"sender_uuid": "u", "sender_epoch": 1, "sender_tmux": "x", "receiver_tmux": "alpha", "receiver_key": "k",
                           "receiver_epoch": 1, "resume_generation": 1}
                reply = await bare._send("POST", "/api/v1/crosstalk/peer-control", token, control)
                assert b"peer_unpaired" not in reply.body, reply.body
            finally:
                await transport.close()
            await release(p)
            with closing(w.b_open()) as conn:
                row = peer_hosts.get(conn, C, include_mesh=True)
            reply = await peer_route_guard.forward_reply(NOTE_RULE, row, "/sessions/alpha/note", {"body": "hi", "expected_revision": 0})
            assert reply.status_code == 200 and json.loads(reply.body)["revision"] == 1, reply.body
            with closing(connect(w.c_path, create=False)) as conn:
                assert "hi" in str([tuple(r) for r in conn.execute("SELECT * FROM session_notes").fetchall()])
            await release(p)
            await p.listeners["c"].stop()
            monkeypatch.setattr(mesh_peers, "CONNECT_SECONDS", 1.0)
            looked_up: list = []
            real_client = w.links_b.client
            monkeypatch.setattr(w.links_b, "client", lambda iid: looked_up.append(iid) or None)
            with pytest.raises(Exception) as caught:
                await peer_route_guard.forward_reply(NOTE_RULE, row, "/sessions/alpha/note", {"body": "x", "expected_revision": 1})
            assert caught.value.status_code == 503 and "cannot be reached from this computer right now" in json.dumps(caught.value.detail)
            assert looked_up and set(looked_up) <= {C}, looked_up

    asyncio.run(scenario())

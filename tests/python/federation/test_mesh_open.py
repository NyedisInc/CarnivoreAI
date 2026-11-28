
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import tempfile
import time
from contextlib import closing
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mopen_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mopen_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

from src.core.computers import commit, mesh  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.federation import mesh_peers, mesh_powers, peer_client, peer_hosts, peer_sockets  # noqa: E402
from src.core.federation.mesh_client import MeshPeerClient, MeshTransport  # noqa: E402
from src.core.federation.peer_link import CONNECTED  # noqa: E402
from src.core.pack.machines import restrictions as restrictions_mod, runtime as machines_runtime  # noqa: E402
from src.core.relay_identity.device_key import DeviceKey, b64url  # noqa: E402
from tests.python.computers.test_mesh_links import A, B, C, _inputs, _wait, root  # noqa: E402,F401,F811
from tests.python.federation.test_mesh_revocation import _linked, _merge, _serving, _world  # noqa: E402
from tests.python.federation import test_mesh_revocation as rev  # noqa: E402
from tests.python.pack import test_settings_signing as ss  # noqa: E402

TIGHTEN = "/federation/pack/restrictions/tighten"
RESERVE = "/federation/pack/reserve"



def test_a_failed_star_commit_puts_a_prior_mesh_row_back_and_purges_nothing(tmp_path, monkeypatch):
    folder = tmp_path / "state"
    folder.mkdir()
    ensure_db_migrated(folder)
    path = db_path_for(folder)
    peer = commit.PeerId(install_id="iid-c", label="host-b", public_key=b64url(bytes(32)), cert_der=b"der", link_fid="fid-c", grant_id="g-remote")
    with closing(connect(path, create=False)) as conn:
        peer_hosts.upsert_mesh(conn, install_id="iid-c", label="mesh-c", grant_id="g-mesh", fid="fid-mesh")
        before = peer_hosts.get(conn, "iid-c", include_mesh=True)
        undo = commit._Undo(lambda: connect(path, create=False))
        commit._write_grant_pair(conn, undo, peer=peer, own_grant_id="g-own", label="host-b", initiator=True)
        star = peer_hosts.get(conn, "iid-c")
        assert star is not None and star.back_kind != "mesh"
    deleted: list = []
    real_delete = peer_hosts.delete
    monkeypatch.setattr(peer_hosts, "delete", lambda conn, iid: deleted.append(iid) or real_delete(conn, iid))
    undo.run()
    with closing(connect(path, create=False)) as conn:
        after = peer_hosts.get(conn, "iid-c", include_mesh=True)
    assert deleted == [], "the undo deleted a host row (which purges that computer's stats rollups)"
    assert after is not None and after.back_kind == "mesh"
    assert (after.key, after.label, after.peer_grant_id, after.peer_fid) == (before.key, before.label, before.peer_grant_id, before.peer_fid)



def test_a_replaced_session_closes_its_own_grant_id(monkeypatch):
    closed: list = []

    async def spy(gid: str) -> None:
        closed.append(gid)

    monkeypatch.setattr(peer_sockets, "close_grant", spy)

    async def ended() -> None:
        return None

    def session(gid: str) -> SimpleNamespace:
        return SimpleNamespace(peer="iid-c", extra={"grant_id": gid}, mux=SimpleNamespace(wait_closed=ended))

    old, new = session("g-old"), session("g-new")
    links = object.__new__(mesh.MeshLinks)
    links._sessions = {"iid-c": new}
    asyncio.run(links._on_closed(old))
    assert closed == ["g-old"]
    assert links._sessions == {"iid-c": new}



def test_a_star_unpair_gives_the_live_mesh_session_its_row(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    with closing(w.b_open()) as conn:
        peer_hosts.upsert(conn, install_id=C, label="c-star", grant_id="g-star", fid="fid-star", initiator=True)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            await _wait(lambda: C in p.links["b"]._sessions and C in w.reg_b._star)
            with closing(w.b_open()) as conn:
                assert peer_hosts.get(conn, C, include_mesh=True).back_kind != "mesh"
            assert not w.reg_b.holds(C)
            with closing(w.b_open()) as conn:
                assert peer_hosts.delete(conn, C)
            await mesh_peers.star_row_gone(C)
            with closing(w.b_open()) as conn:
                assert peer_hosts.get(conn, C, include_mesh=True).back_kind == "mesh"
            await _wait(lambda: w.reg_b.state(C) == CONNECTED, 5.0)

    asyncio.run(scenario())



def test_a_star_row_written_over_a_live_mesh_session_gives_it_a_row_back(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            await _wait(lambda: w.reg_b.holds(C) and w.reg_b.state(C) == CONNECTED, 8.0)
            assert C not in w.reg_b._star
            with closing(w.b_open()) as conn:
                peer_hosts.upsert(conn, install_id=C, label="c-star", grant_id="g-star", fid="fid-star", initiator=True)
                assert peer_hosts.delete(conn, C)
            await mesh_peers.star_row_gone(C)
            with closing(w.b_open()) as conn:
                assert peer_hosts.get(conn, C, include_mesh=True).back_kind == "mesh"

    asyncio.run(scenario())


def test_a_swept_star_join_over_a_live_mesh_session_keeps_its_stats(tmp_path, monkeypatch):
    from src.core.computers import store

    folder = tmp_path / "state"
    folder.mkdir()
    ensure_db_migrated(folder)
    path = db_path_for(folder)
    purged: list = []
    real_purge = peer_hosts.purge_rows
    monkeypatch.setattr(peer_hosts, "purge_rows", lambda conn, iid: purged.append(iid) or real_purge(conn, iid))
    pack = SimpleNamespace(mint=lambda _d: None)
    row = store.LinkRow("iid-c", "member", "tls", "", join_kind="new", cert_der=b"d", cert_sha256="s", link_fid="f", addresses=(), link_port=None,
                        inbound_control=1, joined_at="2026-01-01T00:00:00+00:00")
    with closing(connect(path, create=False)) as conn:
        for keep in (True, False):
            peer_hosts.upsert(conn, install_id="iid-c", label="c", grant_id="g", fid="f", initiator=False)
            commit._revert_rows(conn, row, pack, "me", keep_stats=keep)
            assert peer_hosts.get(conn, "iid-c", include_mesh=True) is None
            assert purged == (["iid-c"] if not keep else [])
            purged.clear()
    monkeypatch.setattr(mesh_peers, "REGISTRY", SimpleNamespace(holds=lambda iid: iid == "iid-c"))
    assert mesh_peers.holds_live("iid-c") and not mesh_peers.holds_live("iid-x")



def test_the_callers_real_takeover_hold_pauses_its_links_and_resumes_on_the_claimants_list(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    D = "install-d"
    monkeypatch.setitem(ss.IDS, "d", D)
    monkeypatch.setitem(ss.LABELS, "d", "fourth")
    monkeypatch.setitem(ss.KEYS, "d", DeviceKey.from_seed(bytes([4]) * 32))
    monkeypatch.setitem(ss.PUB, D, b64url(ss.KEYS["d"].raw_pub))

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, only=("a", "b", "c", "d"), meshers=("b", "c", "d")) as p:
            L, pack = p.links, p.pack
            monkeypatch.setattr(mesh, "_ACTIVE", L["c"])
            try:
                await _wait(lambda: C in L["b"]._sessions and B in L["c"]._sessions and w.reg_b.state(C) == CONNECTED)
                assert p.alpha.refresh_roster(_inputs(p.idents, p.ports, ("a", "b", "c", "d")), eligible={D: True}).startswith("bump:")
                for name in ("b", "c", "d"):
                    for peer, post, caps in pack[name]._connected():
                        if peer != A:
                            await pack[name].beat(peer, post, caps)
                pack["d"].custody.takeover_on = lambda: True
                assert pack["d"].custody.claim()
                L["b"]._schedule_fetch = lambda *a, **k: None
                rev_roster, rsig = rev.roster_doc.from_wire(pack["d"].custody.roster_wire())
                assert pack["b"].custody.adopt_alpha(pack["d"].custody.settings(), rev.settings_sign.signature_from(
                    pack["d"].custody.state.settings_signature()), rev_roster, rsig, rev.settings_sign.CLAIM, C)
                asked: list = []
                real_ensure = w.reg_b.ensure
                w.reg_b.ensure = lambda *a, **k: asked.append(a) or real_ensure(*a, **k)
                await L["b"].list_changed()
                assert L["b"]._grace_until is not None
                assert w.reg_b.state(C) == "disconnected" and w.reg_b._paused
                started = time.monotonic()
                assert await w.reg_b.connect(C) is None
                assert time.monotonic() - started < 0.5 and asked == []
                assert pack["b"].custody.merge_roster_v2(pack["d"].custody.roster_v2_wire(), D)
                await L["b"].list_changed()
                assert L["b"]._grace_until is None
                await _wait(lambda: w.reg_b.state(C) == CONNECTED, 5.0)
                assert not w.reg_b._paused
            finally:
                monkeypatch.setattr(mesh, "_ACTIVE", None)

    asyncio.run(scenario())



def _wire_c_pack(monkeypatch, tmp_path):
    (tmp_path / "cwire").mkdir()
    rt = ss.make_pack(tmp_path / "cwire", {})["c"]
    monkeypatch.setattr(machines_runtime, "wiring", lambda: SimpleNamespace(runtime=rt, sync_scopes=lambda: None))
    return rt


async def _call(session, token, method, path, body, dir_):
    transport = MeshTransport(session, B, dir_)
    try:
        route = await transport.establish()
        client = MeshPeerClient(route, session=session, self_iid=B, sign=ss.KEYS["b"].sign, trusted=lambda _p: None)
        reply = await client._send(method, peer_client._url(path), token, body)
        try:
            return reply.status_code, json.loads(reply.body)
        except ValueError:
            return reply.status_code, {}
    finally:
        await transport.close()


def _code(parsed) -> str:
    detail = parsed.get("detail", parsed)
    return detail.get("code", "") if isinstance(detail, dict) else ""


LOOSENINGS = [
    ({"max_agents": 2}, {"max_agents": None}),
    ({"may_host_agents": False}, {"may_host_agents": True}),
    ({"allowed_projects": ["p1"]}, {"allowed_projects": []}),
    ({"allowed_projects": ["p1"]}, {"allowed_projects": ["p1", "p2"]}),
    ({}, {"may_receive_credentials": True}),
]


def test_a_member_may_tighten_but_never_loosen_or_edit_a_reserve(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    monkeypatch.setattr(mesh_powers, "OPEN_POWERS", frozenset({mesh_powers.MESH_LINK, mesh_powers.MESH_SESSIONS, mesh_powers.MESH_TIGHTEN}))
    rt = _wire_c_pack(monkeypatch, tmp_path)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            await _linked(p, w)
            sess = p.links["b"]._sessions[C]
            token = await w.reg_b.client(C).bearer()
            d = root / "b"

            async def call(method, path, body):
                return await _call(sess, token, method, path, body, d)

            status, parsed = await call("PUT", TIGHTEN, {"patch": {"max_agents": 2}})
            assert status == 200 and rt.state.restrictions().max_agents == 2, (status, parsed)
            for setup, bad in LOOSENINGS:
                rt.state.save_restrictions(restrictions_mod.merged(restrictions_mod.Restrictions(), setup))
                held = rt.state.restrictions()
                status, parsed = await call("PUT", TIGHTEN, {"patch": bad})
                assert status == 403 and _code(parsed) == "pack_restricted", (bad, status, parsed)
                assert rt.state.restrictions() == held, bad
            held_reserve = rt.state.reserve()
            status, parsed = await call("PUT", TIGHTEN, {"patch": {"in_use": {"cpu_pct": 50}}})
            assert status == 422 and _code(parsed) == "restrictions_invalid" and rt.state.reserve() == held_reserve, (status, parsed)
            status, _ = await call("PUT", TIGHTEN, {"patch": {}, "reserve": {"in_use": {"cpu_pct": 50}}})
            assert status == 400 and rt.state.reserve() == held_reserve
            status, parsed = await call("PUT", RESERVE, {"patch": {"in_use": {"cpu_pct": 50}}})
            assert status == 403 and _code(parsed) == "mesh_power_refused" and rt.state.reserve() == held_reserve, (status, parsed)
            rt.state.save_restrictions(restrictions_mod.merged(restrictions_mod.Restrictions(), {"max_agents": 1}))
            monkeypatch.setattr(rt.state, "restrictions", lambda: restrictions_mod.Restrictions())
            status, parsed = await call("PUT", TIGHTEN, {"patch": {"may_install_tools": False}})
            assert status == 200, (status, parsed)
            stored = restrictions_mod.from_dict(rt.state._block().get("restrictions"))
            assert stored.max_agents == 1 and stored.may_install_tools is False, stored
            inputs = [dataclasses.replace(i, one_way=True) if i.install_id == B else i for i in _inputs(p.idents, p.ports)]
            _merge(p, ("b", "c"), inputs)
            await rev._changed(p, "c", "b")
            await _wait(lambda: w.reg_b._entries.get(C) is not None and w.reg_b._entries[C].link is None, 3.0)
            transport = MeshTransport(sess, B, d)
            try:
                bare = MeshPeerClient(await transport.establish(), session=sess, self_iid=B, sign=ss.KEYS["b"].sign,
                                      trusted=lambda _p: p.links["b"]._lst)
                fresh = await bare.bearer(force=True)
                reply = await bare._send("PUT", peer_client._url(TIGHTEN), fresh, {"patch": {"max_agents": 0}})
                assert reply.status_code == 403 and b"computer_one_way" in reply.body, reply.body
            finally:
                await transport.close()

    asyncio.run(scenario())

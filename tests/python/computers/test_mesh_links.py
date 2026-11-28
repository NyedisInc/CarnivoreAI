
from __future__ import annotations

import asyncio
import contextlib
import shutil
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401, E402
from src.core.computers import mesh, takeover_walk  # noqa: E402
from src.core.computers.link_listener import ALERTED  # noqa: E402
from src.core.computers.member_listener import MemberListener, Rendezvous  # noqa: E402
from src.core.computers.mux import frames as mf  # noqa: E402
from src.core.computers.mux.session import StreamReset  # noqa: E402
from src.core.computers.runtime import ComputersRuntime  # noqa: E402
from src.core.computers.takeover_driver import TakeoverDriver, v1_only  # noqa: E402
from src.core.computers.tls_identity import client_link_ctx, ensure_link_identity  # noqa: E402
from src.core.pack.machines import capabilities, roster_doc, roster_v2, settings_sign  # noqa: E402
from src.core.relay_identity.device_key import DeviceKey, b64url  # noqa: E402
from tests.python.pack import test_settings_signing as ss  # noqa: E402
from tests.python.pack.test_settings_signing import CAPS, IDS, make_pack  # noqa: E402
from tests.python.pack.test_takeover_v2 import _computers  # noqa: E402

A, B, C = IDS["a"], IDS["b"], IDS["c"]
V2_CAPS = CAPS + [capabilities.CAP_ROSTER, capabilities.CAP_ROSTER_V2, capabilities.CAP_MESH]


async def _wait(predicate, seconds: float = 8.0) -> None:
    for _ in range(int(seconds / 0.02)):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached")


async def _spread(pack, rounds: int = 4) -> None:
    for _ in range(rounds):
        for name in IDS:
            for peer, post, caps in pack[name]._connected():
                await pack[name].beat(peer, post, caps)


def _inputs(idents, ports, only=("a", "b", "c"), certs=None, next_certs=None):
    certs, next_certs = certs or {}, next_certs or {}
    return [roster_doc.RosterInput(install_id=IDS[n], label=n, fed_public_key=ss.PUB[IDS[n]], cert=certs.get(n, idents[n].cert.der),
                                   next_cert=next_certs.get(n),
                                   addresses=("127.0.0.1",), link_port=ports.get(n, 47110), relay_id=None, capabilities=tuple(V2_CAPS))
            for n in only]


@pytest.fixture()
def root():
    path = Path(tempfile.mkdtemp(prefix="ml"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _no_db():
    raise sqlite3.OperationalError("no database in this test")


@contextlib.asynccontextmanager
async def _pair(root, tmp_path, only=("a", "b", "c"), meshers=("b", "c"), clocks=None, attach=(), hooks=None):
    pack = make_pack(tmp_path, {}, {n: V2_CAPS for n in IDS})
    idents = {}
    for n in IDS:
        (root / n).mkdir(mode=0o700)
        idents[n] = ensure_link_identity(ss.KEYS[n], IDS[n], root / n)
    listeners, links, ports, nss = {}, {}, {}, {}

    async def _follows():
        return {"follows": A}

    for n in meshers:
        listeners[n] = MemberListener(identity=idents[n], rendezvous=Rendezvous(), host="127.0.0.1", follow_hello=lambda: _follows())
        assert await listeners[n].bind(0)
        ports[n] = listeners[n].port
    alpha = pack["a"]
    assert alpha.refresh_roster(_inputs(idents, ports, only)) == "bump:first"
    await _spread(pack)
    for n in meshers:
        held = pack[n].custody.held_lists()
        assert isinstance(held[0], roster_v2.RosterV2) and held[0].entry(C).mesh
        await listeners[n].set_pins([idents["a"].cert], [idents[o].cert for o in meshers if o != n])
    for n in attach:
        async def no_sync(_flag, n=n) -> None:
            pass

        ns = SimpleNamespace(_roster=SimpleNamespace(held_lists=pack[n].custody.held_lists,
                                                     _wired=lambda n=n: SimpleNamespace(runtime=SimpleNamespace(custody=pack[n].custody))),
                             member_listener=listeners[n], identity=idents[n], iid=IDS[n], takeover=None, notify=lambda _t: None,
                             _roster_cache=None, _sync_member_listener=no_sync,
                             open_db=_no_db, fed_dir=root / n, fed_key=ss.KEYS[n])
        ns.after_roster_change = lambda ns=ns: ComputersRuntime.after_roster_change(ns)
        mesh.attach(ns)
        assert mesh._ACTIVE is not None
        links[n], nss[n] = mesh._ACTIVE, ns
    for n in meshers:
        if n in attach:
            continue

        async def changed(n=n):
            await links[n].list_changed()

        extra = {"clock": clocks[n]} if clocks and n in clocks else {}
        wanted = dict((hooks or {}).get(n, {}))
        bind = wanted.pop("bind", None)
        extra.update(wanted)
        links[n] = mesh.MeshLinks(identity=idents[n], iid=IDS[n], listener=listeners[n], custody=lambda n=n: pack[n].custody,
                                  after_change=changed, star_linked=lambda _iid: 0.0, backoff=lambda _a: 0, stagger=0.0, jitter=0.0, **extra)
        if bind is not None:
            bind(links[n])
        links[n].start()
    await asyncio.gather(*(links[n].list_changed() for n in meshers))
    try:
        yield SimpleNamespace(pack=pack, idents=idents, listeners=listeners, links=links, ports=ports, alpha=alpha, nss=nss)
    finally:
        await mesh.detach()
        for n in meshers:
            if n not in attach:
                await links[n].stop()
            await listeners[n].stop()


def test_two_members_link_dedupe_stay_locked_down_and_follow_the_list(monkeypatch, tmp_path, root):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(mesh, "FETCH_DEBOUNCE", 0.0)

    async def scenario() -> None:
        async with _pair(root, tmp_path) as p:
            pack, idents, listeners, links, ports, alpha = p.pack, p.idents, p.listeners, p.links, p.ports, p.alpha

            def converged() -> bool:
                sb, sc = links["b"]._sessions.get(C), links["c"]._sessions.get(B)
                return sb is not None and sc is not None and not sb.mux.closed.is_set() and not sc.mux.closed.is_set()

            for _ in range(2):
                await _wait(converged)
                await asyncio.sleep(0.5)
                assert converged() and len(links["b"]._sessions) == 1 and len(links["c"]._sessions) == 1
                sb, sc = links["b"]._sessions[C], links["c"]._sessions[B]
                assert sb.dialed_by_me is not sc.dialed_by_me
                assert sb.mux._w.get_extra_info("sockname") == sc.mux._w.get_extra_info("peername")
                if _ == 0:
                    await sb.mux.close(mf.GO_NORMAL)
                    await _wait(lambda: sc.mux.closed.is_set())
            sb = links["b"]._sessions[C]
            stream = await sb.mux.open("peer-api")
            with pytest.raises(StreamReset) as caught:
                await stream.read()
            assert caught.value.reason == mf.RST_UNAVAILABLE
            stream = await sb.mux.open("mesh-other")
            with pytest.raises(StreamReset) as caught:
                await stream.read()
            assert caught.value.reason == mf.RST_UNKNOWN
            entry = alpha.custody.roster_v2().entry(B)
            ok, hello = await takeover_walk.probe(entry, idents["c"])
            assert ok and hello is not None and hello.get("follows") == A
            plain = MemberListener(identity=idents["b"], rendezvous=Rendezvous(), host="127.0.0.1")
            assert await plain.bind(0)
            await plain.set_pins([idents["c"].cert])
            ctx = client_link_ctx(idents["c"], [idents["b"].cert])
            ctx.set_alpn_protocols([mesh.MESH_ALPN])
            reader, writer = await asyncio.open_connection("127.0.0.1", plain.port, ssl=ctx, server_hostname="127.0.0.1")
            before = dict(links["c"]._sessions)
            assert await links["c"].serve(reader, writer) == ALERTED
            assert links["c"]._sessions == before
            await plain.stop()
            first = pack["c"].custody.roster_v2().generation
            assert alpha.refresh_roster(_inputs(idents, ports), eligible={B: True}).startswith("bump:")
            assert pack["b"].custody.merge_roster_v2(alpha.custody.roster_v2_wire(), A)
            newer_generation = pack["b"].custody.roster_v2().generation
            assert newer_generation > first and pack["c"].custody.roster_v2().generation == first
            await links["b"].list_changed()
            await _wait(lambda: pack["c"].custody.roster_v2().generation == newer_generation)
            sc = links["c"]._sessions[B]
            await _wait(converged)
            assert alpha.refresh_roster(_inputs(idents, ports, only=("a", "b"))).startswith("bump:")
            assert pack["b"].custody.merge_roster_v2(alpha.custody.roster_v2_wire(), A)
            await links["b"].list_changed()
            await asyncio.wait_for(sc.mux.closed.wait(), 5)
            assert sc.mux.goaway_reason == mf.GO_REMOVED
            assert links["b"]._sessions == {}
            links["c"]._dialer.kick()
            await asyncio.sleep(1.0)
            assert links["b"]._sessions == {}
            assert links["b"].iid_for_sha(idents["c"].cert.cert_sha256) is None
            assert links["b"].relayed() == frozenset() and links["c"].relayed() == frozenset()

    asyncio.run(scenario())


def _v2(links=None, mesh_off=()):
    idents = {}
    d = Path(tempfile.mkdtemp(prefix="ml"))
    try:
        for n in IDS:
            (d / n).mkdir(mode=0o700)
            idents[n] = ensure_link_identity(ss.KEYS[n], IDS[n], d / n)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    inputs = [roster_doc.RosterInput(install_id=IDS[n], label=n, fed_public_key=ss.PUB[IDS[n]], cert=idents[n].cert.der, next_cert=None,
                                     addresses=("127.0.0.1",), link_port=47110, relay_id=None,
                                     capabilities=tuple(c for c in V2_CAPS if not (IDS[n] in mesh_off and c == capabilities.CAP_MESH))) for n in IDS]
    return roster_v2.plan_v2(None, inputs, alpha=A, link_peers=links), idents


def test_allowed_peers_is_the_list_and_nothing_else(monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    lst, idents = _v2()
    fid = idents["b"].cert.link_fid
    assert mesh.allowed_peers(lst, B, fid) == {idents["c"].cert.cert_sha256: C}
    assert mesh.allowed_peers(lst, A, idents["a"].cert.link_fid) == {}
    own_off, _ = _v2({B: False})
    assert mesh.allowed_peers(own_off, B, fid) == {}
    peer_off, _ = _v2({C: False})
    assert mesh.allowed_peers(peer_off, B, fid) == {}
    no_mesh, _ = _v2(mesh_off=(C,))
    assert mesh.allowed_peers(no_mesh, B, fid) == {}
    assert mesh.allowed_peers(lst.as_v1(), B, fid) == {}
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert mesh.allowed_peers(lst, B, fid) == {}


def test_relay_stays_on_the_v1_set_and_a_dark_switch_reads_the_stored_roster(monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    lst = roster_v2.plan_v2(None, _computers(18), alpha=A)
    v1_ids = set(lst.order()[:16])
    calls = []

    async def spy(entry, ctx):
        calls.append(entry.install_id)
        return None

    guarded = v1_only(spy, lambda: v1_ids)
    assert v1_only(None, lambda: v1_ids) is None

    async def go() -> None:
        with pytest.raises(ValueError):
            await guarded(lst.computers[17], None)
        assert calls == []
        await guarded(lst.computers[1], None)
        assert calls == [lst.computers[1].install_id]

    asyncio.run(go())
    stored = object()
    custody = SimpleNamespace(roster=lambda: stored, held_lists=lambda: None)
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert TakeoverDriver._lists(custody) is stored


def _identity_in(root: Path, name: str, key, iid: str):
    (root / name).mkdir(mode=0o700)
    return ensure_link_identity(key, iid, root / name)


def test_a_rotated_certificate_closes_the_live_session_and_the_old_one_is_refused(monkeypatch, tmp_path, root):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(mesh, "FETCH_DEBOUNCE", 0.0)

    async def scenario() -> None:
        async with _pair(root, tmp_path) as p:
            links, idents, ports, alpha = p.links, p.idents, p.ports, p.alpha
            await _wait(lambda: C in links["b"]._sessions and B in links["c"]._sessions)
            sb, sc = links["b"]._sessions[C], links["c"]._sessions[B]
            old_sha = idents["c"].cert.cert_sha256
            assert sb.cert_sha == old_sha
            fresh = _identity_in(root, "c2", ss.KEYS["c"], C)
            assert fresh.cert.cert_sha256 != old_sha
            assert alpha.refresh_roster(_inputs(idents, ports, next_certs={"c": fresh.cert.der})).startswith("bump:")
            assert p.pack["b"].custody.merge_roster_v2(alpha.custody.roster_v2_wire(), A)
            await links["b"].list_changed()
            await asyncio.sleep(0.3)
            assert links["b"]._sessions.get(C) is sb and not sb.mux.closed.is_set()
            calls = []
            real = p.listeners["b"]._mesh_iid
            p.listeners["b"]._mesh_iid = lambda sha: calls.append(real(sha)) or calls[-1]
            assert alpha.refresh_roster(_inputs(idents, ports, certs={"c": fresh.cert.der})).startswith("bump:")
            assert p.pack["b"].custody.merge_roster_v2(alpha.custody.roster_v2_wire(), A)
            await links["b"].list_changed()
            await asyncio.wait_for(sc.mux.closed.wait(), 5)
            assert sc.mux.goaway_reason == mf.GO_REMOVED and sb.mux.closed.is_set()
            assert links["b"].iid_for_sha(old_sha) is None and links["b"].iid_for_sha(fresh.cert.cert_sha256) == C
            links["c"]._dialer.kick()
            await _wait(lambda: links["c"]._dialer._dials[B].alerts >= 1 and None in calls)
            assert links["b"]._sessions == {}
            await links["b"].stop()
            assert await links["b"].register(sb) is False and links["b"]._sessions == {}

    asyncio.run(scenario())


def test_takeover_keeps_mesh_links_until_the_claimants_list_arrives(monkeypatch, tmp_path, root):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(mesh, "FETCH_DEBOUNCE", 0.0)
    D = "install-d"
    monkeypatch.setitem(ss.IDS, "d", D)
    monkeypatch.setitem(ss.LABELS, "d", "fourth")
    monkeypatch.setitem(ss.KEYS, "d", DeviceKey.from_seed(bytes([4]) * 32))
    monkeypatch.setitem(ss.PUB, D, b64url(ss.KEYS["d"].raw_pub))
    now = [1000.0]

    def adopt_claim(taker, claimant) -> None:
        cc = claimant.custody
        roster, rsig = roster_doc.from_wire(cc.roster_wire())
        assert taker.custody.adopt_alpha(cc.settings(), settings_sign.signature_from(cc.state.settings_signature()), roster, rsig,
                                         settings_sign.CLAIM, C)

    async def scenario() -> None:
        async with _pair(root, tmp_path, only=("a", "b", "c", "d"), meshers=("b", "c", "d"), attach=("b",), clocks={"d": lambda: now[0]}) as p:
            L, pack = p.links, p.pack
            await _wait(lambda: len(L["b"]._sessions) == 2 and len(L["c"]._sessions) == 2 and len(L["d"]._sessions) == 2)
            sbd = L["b"]._sessions[D]
            assert p.alpha.refresh_roster(_inputs(p.idents, p.ports, ("a", "b", "c", "d")), eligible={C: True}).startswith("bump:")
            for name in ("b", "c", "d"):
                for peer, post, caps in pack[name]._connected():
                    if peer != A:
                        await pack[name].beat(peer, post, caps)
            pack["c"].custody.takeover_on = lambda: True
            assert pack["c"].custody.claim()
            await L["c"].list_changed()
            adopt_claim(pack["b"], pack["c"])
            await p.nss["b"].after_roster_change()
            assert L["b"]._grace_until is not None and L["b"]._sessions.get(D) is sbd and not sbd.mux.closed.is_set()
            await _wait(lambda: isinstance(pack["b"].custody.held_lists()[0], roster_v2.RosterV2) and pack["b"].custody.held_lists()[0].alpha == C)
            await _wait(lambda: L["b"]._grace_until is None)
            assert L["b"]._sessions.get(D) is sbd and not sbd.mux.closed.is_set()
            L["d"]._schedule_fetch = lambda *a, **k: None
            adopt_claim(pack["d"], pack["c"])
            await L["d"].list_changed()
            assert L["d"]._grace_until is not None and all(not s.mux.closed.is_set() for s in L["d"]._sessions.values())
            now[0] += mesh.TAKEOVER_GRACE_SECONDS + 1
            await L["d"].list_changed()
            await asyncio.wait_for(sbd.mux.closed.wait(), 5)
            assert sbd.mux.goaway_reason == mf.GO_REMOVED

    asyncio.run(scenario())


def test_a_refusal_is_remembered_on_the_claimed_sha_as_well_as_the_served_one(monkeypatch, tmp_path, root):
    lst, idents = _v2()
    served = roster_v2.to_wire_v2(lst, {"signer": A, "sig": "x"})
    served_sha = roster_v2.sha(roster_v2.blob(served))
    claim = {"g": 9, "t": 9, "sha": "0" * 64}
    calls = []

    async def fake_fetch(mux, summary):
        calls.append(1)
        return served

    monkeypatch.setattr(mesh, "fetch_list", fake_fetch)

    async def scenario() -> None:
        (root / "b").mkdir(mode=0o700)
        ident = ensure_link_identity(ss.KEYS["b"], B, root / "b")
        listener = MemberListener(identity=ident, rendezvous=Rendezvous(), host="127.0.0.1")
        links = mesh.MeshLinks(identity=ident, iid=B, listener=listener, custody=lambda: SimpleNamespace(merge_roster_v2=lambda raw, peer: False),
                               after_change=lambda: asyncio.sleep(0), star_linked=lambda _i: 0.0)
        links._sessions[C] = SimpleNamespace(mux=None)
        links._consider(C, claim, 0.0)
        await links._fetching[C]
        assert links._refused[C] == {served_sha, claim["sha"]} and len(calls) == 1
        links._consider(C, claim, 0.0)
        assert C not in links._claims and len(calls) == 1

    asyncio.run(scenario())

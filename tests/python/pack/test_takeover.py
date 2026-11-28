
from __future__ import annotations

import asyncio
import base64
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401, E402
from fastapi import HTTPException  # noqa: E402

from src.api import federation_pack_skills_routes, pack_machines_routes  # noqa: E402
from src.core.api_keys import fence  # noqa: E402
from src.core.computers.member_listener import MemberListener, Rendezvous  # noqa: E402
from src.core.computers.takeover_walk import LinkHistory, Walker  # noqa: E402
from src.core.computers.tls_identity import pinned_certs  # noqa: E402
from src.core.pack.machines import config_state, interim_policy, roster_doc, settings_doc, settings_sign  # noqa: E402
from src.core.pack.machines.interim_policy import Peer, Standing, Walk  # noqa: E402
from tests.python.computers.test_tls_link import MAIN_IID, world  # noqa: E402, F401
from tests.python.pack.test_roster import ROSTER_CAPS, _inputs, _setup  # noqa: E402
from tests.python.pack.test_settings_signing import IDS, KEYS, PUB, mesh  # noqa: E402

A, B, C = IDS["a"], IDS["b"], IDS["c"]
ARM = interim_policy.ARM_SECONDS


def _world(tmp_path, order=("a", "b", "c"), eligible=("a", "b", "c"), home=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    pack = _setup(tmp_path, {n: ROSTER_CAPS for n in IDS})
    pack["a"].refresh_roster(_inputs(), order=[IDS[n] for n in order], eligible={IDS[n]: True for n in eligible})
    mesh(pack)
    if home is not None:
        held = pack["a"].custody.roster()
        rehomed = roster_doc.Roster(**{**held.model_dump(), "home": home})
        wire = roster_doc.to_wire(rehomed, roster_doc.sign(rehomed, KEYS["a"], A).to_dict())
        for n in IDS:
            pack[n].state.save_roster(wire)
    for n in IDS:
        pack[n].custody.takeover_on = lambda: True
    return pack


def _standing(*, span=ARM + 1, reachable=(), claim=(), silent=None, now=1000.0, age=5.0):
    peers = {IDS[n]: Peer(n in reachable, n in claim) for n in IDS}
    return Standing(now=now, alpha_span=span, walk=Walk(at=now - age, peers=peers), silent=silent or {})


def _payload(pack, name):
    doc, sig = pack[name].custody.outgoing()
    return doc, sig, pack[name].custody.roster_wire()


def _offer(pack, to, frm, payload, sender=None):
    return pack[to].custody.merge(payload[0], payload[1], IDS[sender or frm], payload[2])


def _master(pack, name):
    return pack[name].custody.settings().master_install_id


def _mutated(payload, change):
    doc = settings_doc.PackSettings(**payload[0])
    raw = payload[2]["roster"]
    edited = {**raw, "computers": [dict(c) for c in raw["computers"]]}
    change(edited)
    roster = roster_doc.Roster(**edited)
    return payload[0], payload[1], roster_doc.to_wire(roster, roster_doc.sign(roster, KEYS["c"], doc.rev[1]).to_dict())


def test_claim_needs_silence_evidence_and_the_content_check(tmp_path, monkeypatch):
    pack = _world(tmp_path, order=("a", "c", "b"), eligible=("b", "c"))
    roster = pack["a"].custody.roster()
    walk = lambda at=1000.0, **peers: Walk(at, {IDS[n]: p for n, p in peers.items()})  # noqa: E731
    down = {"a": Peer(False), "b": Peer(False)}
    ok = lambda **kw: interim_policy.may_claim(roster=roster, self_id=C, alpha=A, alpha_span=kw.get("span", ARM + 1), walk=kw.get("walk", walk(**down)),  # noqa: E731
                                               now=kw.get("now", 1005.0))[0]
    assert ok() and not ok(span=ARM - 1) and not ok(walk=walk(a=Peer(True), b=Peer(False))) and not ok(now=1100.0)
    assert ok(walk=walk(a=Peer(False), b=Peer(True, False)))
    assert pack["c"].custody.claim() and pack["c"].custody.interim()
    claim = _payload(pack, "c")
    for standing, why in ((_standing(span=100.0), "alpha silent for under 5 minutes"), (_standing(reachable=("a",)), "alpha still reachable from b"),
                          (_standing(age=90.0), "walk older than a minute"), (None, "no observation at all")):
        pack["b"].custody.standing = lambda s=standing: s
        assert _offer(pack, "b", "c", claim) is False and _master(pack, "b") == A, why
    stale = settings_doc.PackSettings(master_install_id=C, rev=(pack["b"].custody.settings().rev[0], C))
    stale_roster = roster_doc.Roster(**{**pack["c"].custody.roster().model_dump(), "generation": stale.rev[0]})
    pack["b"].custody.standing = lambda: _standing()
    assert _offer(pack, "b", "c", (stale.model_dump(mode="json"), settings_sign.sign(stale, KEYS["c"], C).to_dict(),
                                   roster_doc.to_wire(stale_roster, roster_doc.sign(stale_roster, KEYS["c"], C).to_dict()))) is False
    assert _master(pack, "b") == A
    swap = lambda r, i, **kw: r["computers"][i].update(kw)  # noqa: E731
    for n, change in enumerate((lambda r: swap(r, 1, cert=base64.b64encode(b"\x09" * 40).decode()), lambda r: swap(r, 2, next_cert=base64.b64encode(b"\x08" * 40).decode()),
                   lambda r: swap(r, 1, fed_public_key=PUB[A]), lambda r: swap(r, 2, takeover_eligible=False), lambda r: r["computers"].reverse(),
                   lambda r: swap(r, 2, relay_id="abc123"), lambda r: r.update(home=C))):
        assert _offer(pack, "b", "c", _mutated(claim, change)) is False, f"mutation {n}"
    assert _master(pack, "b") == A
    assert roster_doc.from_wire({"roster": {**claim[2]["roster"], "computers": [{**claim[2]["roster"]["computers"][0], "relay_id": "a.b"}]}, "sig": claim[2]["sig"]}) is None
    assert _offer(pack, "b", "c", claim) is True and _master(pack, "b") == C and pack["b"].custody.interim()
    other = _world(tmp_path / "x", order=("a", "c", "b"), eligible=("b", "c"))
    other["c"].custody.mint({"placement_mode": "enhanced"}, strict=True)
    other["c"].custody.claim()
    other["b"].custody.standing = lambda: _standing()
    assert _offer(other, "b", "c", _payload(other, "c")) is True
    third = _world(tmp_path / "y", order=("a", "c", "b"), eligible=("b", "c"))
    third["c"].custody.mint({"placement_mode": "enhanced"}, strict=True)
    third["c"].custody.claim()
    third["b"].custody.standing = lambda: _standing()
    monkeypatch.setattr(interim_policy, "SECURITY_FIELDS", ("placement_mode",))
    assert _offer(third, "b", "c", _payload(third, "c")) is False
    blocked = _world(tmp_path / "z")
    blocked["c"].custody.claim()
    blocked["b"].custody.standing = lambda: _standing()
    assert _offer(blocked, "b", "c", _payload(blocked, "c")) is False and _master(blocked, "b") == A


def test_limited_powers_while_interim_and_the_owner_confirm(tmp_path, monkeypatch):
    pack = _world(tmp_path, order=("a", "c", "b"), eligible=("b", "c"))
    pack["c"].custody.claim()
    pack["b"].custody.standing = lambda: _standing()
    assert _offer(pack, "b", "c", _payload(pack, "c")) and pack["b"].custody.interim()
    assert pack["b"].custody.content_alpha() is None and pack["b"].content_alpha() is None and pack["a"].custody.content_alpha() == A
    monkeypatch.setattr("src.core.pack.machines.runtime.wiring", lambda: SimpleNamespace(runtime=pack["b"]))
    principal = SimpleNamespace(is_peer=True, grant=SimpleNamespace(peer_install_id=C))
    with pytest.raises(HTTPException) as refused:
        asyncio.run(federation_pack_skills_routes._alpha(principal))
    assert refused.value.status_code == 403 and refused.value.detail["code"] == "not_alpha"
    raw = pack["c"].custody.roster_wire()["roster"]
    selfhome = roster_doc.Roster(**{**raw, "home": C})
    forged = (pack["c"].custody.outgoing()[0], pack["c"].custody.outgoing()[1], roster_doc.to_wire(selfhome, roster_doc.sign(selfhome, KEYS["c"], C).to_dict()))
    assert _offer(pack, "b", "c", forged) is False and pack["b"].custody.interim()
    assert pack["a"].custody.confirm_local() is False
    assert pack["b"].custody.confirm_local() is True and not pack["b"].custody.interim() and pack["b"].custody.content_alpha() == C
    assert pack["b"].custody.home_state().home_override == C and pack["b"].custody.roster().home == A
    assert pack["c"].custody.interim()
    pack["a"].custody.reclaim_home()
    assert _offer(pack, "b", "a", _payload(pack, "a")) is False and _master(pack, "b") == C
    roster = pack["b"].custody.roster()
    state = interim_policy.HomeState(home_override=C)
    assert interim_policy.meeting_decision(roster=roster, state=state, self_id=C, self_generation=9, other=B, other_generation=50, silent_seconds=ARM)[0] == "stay"
    assert pack["b"].custody.clear_home_override() and pack["b"].custody.interim()
    request = lambda **h: SimpleNamespace(headers={"host": "localhost:5001", **h})  # noqa: E731
    pack_machines_routes._same_origin(request(origin="http://localhost:5001"))
    pack_machines_routes._same_origin(request())
    for headers in ({"origin": "https://evil.example"}, {"sec-fetch-site": "cross-site"}):
        with pytest.raises(HTTPException) as foreign:
            pack_machines_routes._same_origin(request(**headers))
        assert foreign.value.status_code == 403
    assert fence.fenced_family("/api/v1/pack/interim/confirm")
    monkeypatch.setattr(pack_machines_routes, "_wired", lambda: SimpleNamespace(runtime=pack["a"], peers=lambda: [], ))
    with pytest.raises(HTTPException) as nothing:
        asyncio.run(pack_machines_routes.post_interim_confirm(request()))
    assert nothing.value.status_code == 409
    mcp = "".join(p.read_text() for p in Path("src/core/mcp").rglob("*.py"))
    assert "interim" not in mcp and "pack_reconnect_on" not in mcp
    from src.core.computers.takeover_driver import TakeoverDriver

    paused = TakeoverDriver(SimpleNamespace(_roster=SimpleNamespace(_wired=lambda: SimpleNamespace(runtime=pack["b"]))))
    assert asyncio.run(paused.rotation_paused()) is True
    pack["b"].custody.confirm_local()
    assert asyncio.run(paused.rotation_paused()) is False


@pytest.mark.parametrize("home_saw_the_rogue", [True, False])
def test_home_reclaims_over_a_chain_and_a_rogue_that_ran_ahead(tmp_path, home_saw_the_rogue):
    pack = _world(tmp_path, order=("a", "c", "b"), eligible=("b", "c"))
    held = pack["a"].custody.settings().rev[0]
    pack["c"].custody.claim()
    pack["b"].custody.standing = lambda: _standing()
    assert _offer(pack, "b", "c", _payload(pack, "c"))
    for _ in range(50):
        pack["c"].custody.mint({}, strict=True)
    assert _offer(pack, "b", "c", _payload(pack, "c")) and pack["b"].custody.settings().rev[0] == held + 51
    if home_saw_the_rogue:
        assert _offer(pack, "a", "c", _payload(pack, "c")) is False
        assert pack["a"].custody.rival_alpha() == C and pack["a"].custody.seen_generation() == held + 51
    state, roster = pack["a"].custody.home_state(), pack["a"].custody.roster()
    assert not interim_policy.reclaim_due(self_id=A, roster=roster, state=state, master=C, linked_seconds=ARM - 1)
    assert interim_policy.reclaim_due(self_id=A, roster=roster, state=state, master=C, linked_seconds=ARM)
    assert not interim_policy.reclaim_due(self_id=B, roster=roster, state=state, master=C, linked_seconds=ARM)
    assert pack["a"].custody.reclaim_home()
    reclaim = _payload(pack, "a")
    assert reclaim[0]["rev"][0] == (held + 52 if home_saw_the_rogue else held + 1)
    assert _offer(pack, "c", "a", reclaim) and _master(pack, "c") == A and not pack["c"].custody.interim()
    assert _offer(pack, "b", "a", reclaim, sender="c") and _master(pack, "b") == A and not pack["b"].custody.interim()
    expected = (reclaim[0]["rev"][0], pack["a"].custody.roster().issued_at)
    assert pack["c"].custody.home_state().last_home == expected
    assert config_state.ConfigState(lambda: tmp_path / "c.json").takeover_state()[1] == expected
    older = settings_doc.PackSettings(master_install_id=A, rev=(held, A))
    assert pack["c"].custody.merge(older.model_dump(mode="json"), settings_sign.sign(older, KEYS["a"], A).to_dict(), A, reclaim[2]) is False
    state = interim_policy.HomeState(last_home=(10, 1000))
    ok = lambda gen, at: interim_policy.home_document_ok(state=state, interim=True, generation=gen, issued_at=at)[0]  # noqa: E731
    assert not ok(9, 2000) and not ok(11, 1000 - interim_policy.ISSUED_SKEW_SECONDS - 1) and ok(11, 1000 - interim_policy.ISSUED_SKEW_SECONDS) and ok(11, 5000)
    assert not interim_policy.home_document_ok(state=state, interim=False, generation=99, issued_at=9000)[0]


def test_two_alphas_meet_heal_by_generation_then_rank_and_the_vouch(tmp_path):
    z = "install-z"
    pack = _world(tmp_path, home=z)
    now = 1000.0
    history = LinkHistory()
    history.observe([B], 0.0)
    history.observe([B], 30.0)
    history.observe([], 60.0)
    for n in "bc":
        assert pack[n].custody.claim()
    payload = {n: _payload(pack, n) for n in "bc"}
    assert payload["b"][0]["rev"][0] == payload["c"][0]["rev"][0]
    pack["c"].custody.standing = lambda: _standing(silent={B: history.silent(B, 90.0)})
    assert history.silent(B, 90.0) == 60.0 and _offer(pack, "c", "b", payload["b"]) is False and _master(pack, "c") == C
    pack["c"].custody.standing = lambda: _standing(silent={B: history.silent(B, 30.0 + ARM)})
    pack["b"].custody.standing = lambda: _standing(silent={C: ARM + 60.0})
    assert _offer(pack, "b", "c", payload["c"]) is False and _master(pack, "b") == B
    assert _offer(pack, "c", "b", payload["b"]) is True and _master(pack, "c") == B and pack["c"].custody.interim()
    pack["a"].custody.standing = lambda: _standing(silent={B: ARM + 1})
    assert _offer(pack, "a", "b", payload["b"]) is True and _master(pack, "a") == B
    vouched = _world(tmp_path / "v", home=z, order=("a", "c", "b"), eligible=("a", "b", "c"))
    vouched["c"].custody.claim()
    vouched["b"].custody.standing = lambda: _standing()
    assert _offer(vouched, "b", "c", _payload(vouched, "c")) and _master(vouched, "b") == C
    held = vouched["a"].custody.roster()
    vouched["a"].custody.mint({}, strict=True)
    doc, sig = vouched["a"].custody.outgoing()
    newer = roster_doc.Roster(**{**held.model_dump(), "generation": doc["rev"][0], "issued_at": held.issued_at + 5})
    wire = roster_doc.to_wire(newer, roster_doc.sign(newer, KEYS["a"], A).to_dict())
    assert doc["rev"][0] == vouched["b"].custody.settings().rev[0]
    assert _offer(vouched, "b", "a", (doc, sig, wire), sender="b") is False
    assert _offer(vouched, "b", "a", (doc, sig, wire), sender="c") is True and _master(vouched, "b") == A
    assert now


def test_the_walk_over_real_tls_counts_only_a_pinned_certificate(world):
    root, dirs, idents = world
    member_iid = "member-install-bbbb"
    der = lambda who: base64.b64encode(idents[who].cert.der).decode()  # noqa: E731

    def roster_for(port):
        entries = [roster_doc.RosterComputer(install_id=MAIN_IID, fed_public_key=PUB[A], cert=der("main")),
                   roster_doc.RosterComputer(install_id=member_iid, fed_public_key=PUB[B], cert=der("member"), addresses=["127.0.0.1"], link_port=port)]
        return roster_doc.Roster(generation=1, alpha=MAIN_IID, home=MAIN_IID, issued_at=1, computers=entries)

    async def hello():
        return {"follows": member_iid, "generation": 1, "can_claim": True}

    async def run():
        clock = [0.0]
        main_cert = pinned_certs([idents["main"].cert.der], own_link_fid=idents["member"].cert.link_fid)
        answerer = MemberListener(identity=idents["member"], rendezvous=Rendezvous(), host="127.0.0.1", follow_hello=hello)
        assert await answerer.bind(0)
        await answerer.set_pins([], main_cert)
        walker = Walker(identity=idents["main"], self_id=MAIN_IID, clock=lambda: clock[0], roster=lambda: roster_for(answerer.port))
        hellos = await walker.round()
        assert walker.walk.peers[member_iid] == Peer(True, True) and hellos[member_iid]["follows"] == member_iid and walker.alpha_span(member_iid) == 0.0
        port = answerer.port
        await answerer.stop()
        stranger = MemberListener(identity=idents["evil"], rendezvous=Rendezvous(), host="127.0.0.1", follow_hello=hello)
        assert await stranger.bind(port)
        await stranger.set_pins([], main_cert)
        for tick in (30.0, 60.0):
            clock[0] = tick
            assert await walker.round() == {} and walker.walk.peers[member_iid] == Peer(False, False)
        assert walker.alpha_span(member_iid) == 30.0
        await stranger.stop()
        linked = Walker(identity=idents["main"], self_id=MAIN_IID, clock=lambda: 0.0, roster=lambda: roster_for(port), linked=lambda: [member_iid])
        await linked.round()
        assert linked.walk.peers[member_iid].reachable

    asyncio.run(asyncio.wait_for(run(), 30))


def test_observed_span_and_every_alpha_consumer_goes_through_content_alpha():
    clock = [0.0]
    span = interim_policy.ObservedSpan(lambda: clock[0])
    for t in (0.0, 30.0, 60.0, 90.0):
        clock[0] = t
        span.failed()
    assert span.seconds() == 90.0
    clock[0] = 90.0 + interim_policy.GAP_SECONDS + 1
    assert span.seconds() == 0.0
    span.failed()
    assert span.seconds() == 0.0
    clock[0] += 30.0
    span.failed()
    assert span.seconds() == 30.0
    span.reached()
    assert span.seconds() == 0.0
    link_and_status = {
        "src/api/pack_machines_routes.py": "owner edits and the Pack view", "src/core/computers/commit.py": "the join mints its own master",
        "src/core/computers/forget.py": "a leave mints its own master", "src/core/computers/runtime.py": "link rows, the pack view and the HELLO",
        "src/core/computers/takeover_driver.py": "the takeover loop itself", "src/core/computers/mesh.py": "the takeover hold of mesh links (link state, no content)", "src/core/pack/machines/config_state.py": "stores the document",
        "src/core/pack/machines/exchange.py": "the document exchange", "src/core/pack/machines/roster.py": "the machines view",
        "src/core/pack/machines/reconnect_view.py": "names the link and status answer in the machines view",
        "src/core/pack/machines/settings_custody.py": "custody", "src/core/pack/machines/settings_doc.py": "the document",
        "src/core/pack/machines/settings_sign.py": "the judge", "src/core/pack/skills/alerts.py": "text about a refused document",
        "src/core/pack/globalsync/sender.py": "takes is_main and main_id injected; globalsync/wiring.py passes content_alpha",
        "src/api/pack_global_sync_routes.py": "asks the injected sync.is_main, which is content_alpha",
        "src/api/pack_link_peers_routes.py": "an owner edit of a link switch: it needs the document's own master and refuses an interim claimant itself",
        "src/core/pack/relay/member_reach.py": "keys the member id cache on the held document master, so a leave or a join of another Pack never serves it (identity, not content)",
    }
    pattern = re.compile(r"master_install_id|held_alpha\(|\bis_main\b")
    for path in sorted(Path("src").rglob("*.py")):
        text = path.read_text()
        if pattern.search(text) and str(path) not in link_and_status and not str(path).endswith("interim_policy.py"):
            assert "content_alpha" in text, f"{path} reads the Alpha id for content and is not routed through content_alpha()"
    for path in ("src/core/pack/globalsync/wiring.py", "src/core/pack/skills/wiring.py"):
        assert "settings().master_install_id" not in Path(path).read_text().replace("member=runtime.settings().master_install_id != runtime.install_id", "")
    import inspect

    assert "content_alpha" in inspect.getsource(federation_pack_skills_routes._alpha) and "held_alpha(" not in inspect.getsource(federation_pack_skills_routes._alpha)
    assert "held_alpha(" not in Path("src/api/federation_pack_global_routes.py").read_text()


def test_review_fixes_interim_roster_vouch_replay_anchor_and_reach(tmp_path, monkeypatch):
    pack = _world(tmp_path, order=("a", "c", "b"), eligible=("b", "c"))
    pack["c"].custody.claim()
    pack["b"].custody.standing = lambda: _standing()
    assert _offer(pack, "b", "c", _payload(pack, "c")) and pack["b"].custody.interim()
    assert pack["b"].custody.home_state().last_home is not None
    assert not interim_policy.home_document_ok(state=interim_policy.HomeState(), interim=True, generation=3, issued_at=1, held_generation=3)[0]
    assert pack["c"].custody.interim() and pack["c"].custody.refresh_roster(_inputs()) == ""
    raw = pack["c"].custody.roster_wire()["roster"]
    flipped = roster_doc.Roster(**{**raw, "generation": raw["generation"] + 1, "issued_at": raw["issued_at"] + 9,
                                   "computers": [{**c, "takeover_eligible": not c["takeover_eligible"]} for c in raw["computers"]]})
    assert pack["b"].custody.merge_roster(roster_doc.to_wire(flipped, roster_doc.sign(flipped, KEYS["c"], C).to_dict()), C) is False
    other = _world(tmp_path / "v", order=("a", "c", "b"), eligible=("a", "b", "c"))
    other["c"].custody.claim()
    other["b"].custody.standing = lambda: _standing()
    assert _offer(other, "b", "c", _payload(other, "c"), sender="a") is True and _master(other, "b") == C
    from src.core.computers import takeover_walk

    answers, clock = [True], [0.0]

    async def fake_probe(entry, identity, **kw):
        return answers[0], None

    monkeypatch.setattr(takeover_walk, "probe", fake_probe)
    walker = Walker(identity=None, self_id=A, clock=lambda: clock[0], roster=pack["a"].custody.roster)
    for t in (0.0, 30.0, 60.0):
        clock[0] = t
        asyncio.run(walker.round())
    assert walker.reached_seconds(C) == 60.0
    walker.reset()
    assert walker.reached_seconds(C) == 0.0
    answers[0] = False
    clock[0] = 90.0
    asyncio.run(walker.round())
    assert walker.reached_seconds(C) == 0.0

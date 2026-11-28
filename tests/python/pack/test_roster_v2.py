
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401, E402

from src.core.computers import commit, store  # noqa: E402
from src.core.computers.ddl import apply_computer_links  # noqa: E402
from src.core.pack.machines import capabilities, roster_doc, roster_pieces, roster_v2, settings_sign  # noqa: E402
from src.core.relay_identity.device_key import DeviceKey, b64url  # noqa: E402
from tests.python.pack import test_settings_signing as ss  # noqa: E402
from tests.python.pack.test_roster import _inputs  # noqa: E402
from tests.python.pack.test_settings_signing import IDS, make_pack, mesh  # noqa: E402


def _many(count: int):
    base = _inputs(("a",))[0]
    rows = [base]
    for i in range(1, count):
        rows.append(roster_doc.RosterInput(install_id=f"iid-{i:03d}", label=f"c{i}", fed_public_key=base.fed_public_key,
                                           cert=bytes([i % 250 + 1]) * 40, next_cert=None, addresses=(), link_port=47110, relay_id=None))
    return rows


def test_switch_is_off_and_hides_both_names(monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert capabilities.MESH_BUILD_ON is False and capabilities.mesh_on() is False
    assert capabilities.CAP_MESH == "pack.mesh_v1" and capabilities.CAP_ROSTER_V2 == "pack.roster_v2"
    assert not {capabilities.CAP_MESH, capabilities.CAP_ROSTER_V2} & set(capabilities.names())
    assert roster_doc.max_computers() == roster_doc.MAX_COMPUTERS == 16


def test_switch_on_advertises_both_names_and_holds_64(monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    assert {capabilities.CAP_MESH, capabilities.CAP_ROSTER_V2} <= set(capabilities.names())
    assert roster_doc.max_computers() == 64
    with pytest.raises(roster_doc.RosterFull) as full:
        roster_doc.plan(None, _many(65), alpha=IDS["a"], limit=roster_doc.max_computers())
    assert (full.value.count, full.value.limit) == (65, 64)


def test_plan_refuses_the_17th_by_name_and_16_still_plans():
    assert len(roster_doc.plan(None, _many(16), alpha=IDS["a"]).computers) == 16
    with pytest.raises(roster_doc.RosterFull) as full:
        roster_doc.plan(None, _many(17), alpha=IDS["a"])
    assert (full.value.count, full.value.limit) == (17, 16)
    assert len(full.value.left_out) == 1 and full.value.left_out[0] in {i.install_id for i in _many(17)}
    assert str(full.value) == "the pack is full: 17 computers, the limit is 16"
    assert isinstance(full.value, roster_doc.RosterRefused)


def test_alpha_tick_keeps_the_held_roster_and_says_why_and_an_edit_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    pack = make_pack(tmp_path, {}, None)
    mesh(pack)
    a = pack["a"]
    assert a.refresh_roster(_inputs()) == "bump:first"
    held = a.custody.roster_wire()
    assert a.view([]).get("roster_refusal") is None and "roster_refusal" not in a.view([])
    assert a.refresh_roster(_many(17)) == ""
    assert a.custody.roster_wire() == held
    assert a.view([])["roster_refusal"] == {"code": "pack_full", "count": 17, "limit": 16}
    with pytest.raises(roster_doc.RosterFull):
        a.refresh_roster(_many(17), order=[i.install_id for i in _many(17)])
    assert a.refresh_roster(_inputs()) == ""
    assert "roster_refusal" not in a.view([])


def test_removing_a_computer_from_an_over_limit_pack_still_leaves_the_signed_roster(tmp_path, monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    pack = make_pack(tmp_path, {}, None)
    mesh(pack)
    a = pack["a"]
    everyone = _many(18)
    assert a.refresh_roster(everyone[:16]) == "bump:first"
    gone = "iid-005"
    assert a.custody.signing.public_key_for(gone) is not None
    assert a.refresh_roster([i for i in everyone if i.install_id != gone]) == "bump:membership"
    listed = [c.install_id for c in a.custody.roster().computers]
    assert gone not in listed and len(listed) == 15
    assert a.custody.signing.public_key_for(gone) is None
    assert a.view([])["roster_refusal"]["code"] == "pack_full"


def test_exchange_body_never_carries_roster_v2_with_the_switch_off(tmp_path):
    pack = make_pack(tmp_path, {}, None)
    bodies = []
    real = pack["a"]._connected

    def recording():
        def wrap(post):
            async def rec(method, path, body):
                bodies.append(json.loads(json.dumps(body)))
                return await post(method, path, body)
            return rec
        return [(peer, wrap(post), caps) for peer, post, caps in real()]

    pack["a"]._connected = recording
    mesh(pack)
    assert bodies and all("roster_v2" not in b for b in bodies)


def test_switch_off_bodies_are_byte_identical_even_to_a_peer_that_advertises_v2(tmp_path, monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    v2 = ss.CAPS + [capabilities.CAP_ROSTER, capabilities.CAP_ROSTER_V2]
    pack = make_pack(tmp_path, {}, {n: v2 for n in IDS})
    seen, replies = [], []
    real = pack["a"]._connected

    def recording():
        def wrap(post):
            async def rec(method, path, body):
                seen.append(sorted(body))
                status, reply = await post(method, path, body)
                replies.append(sorted(reply))
                return status, reply
            return rec
        return [(peer, wrap(post), caps) for peer, post, caps in real()]

    pack["a"]._connected = recording
    mesh(pack)
    assert pack["a"].refresh_roster(_inputs()) == "bump:first"
    mesh(pack)
    assert seen and all(k == ["roster", "settings", "settings_sig", "snapshot", "want_agents"] for k in seen)
    assert all("roster_v2" not in k for k in replies)
    assert pack["a"].state.stored_roster_v2() is None and "roster_v2" not in pack["a"].state._block()
    assert not {capabilities.CAP_MESH, capabilities.CAP_ROSTER_V2} & set(pack["a"].own_snapshot()["capabilities"])


def _four(monkeypatch, tmp_path, caps_extra=()):
    for name, i in (("d", 4),):
        key = DeviceKey.from_seed(bytes([i]) * 32)
        monkeypatch.setitem(ss.IDS, name, "install-d")
        monkeypatch.setitem(ss.LABELS, name, "fourth")
        monkeypatch.setitem(ss.KEYS, name, key)
        monkeypatch.setitem(ss.PUB, "install-d", b64url(key.raw_pub))
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    v2 = ss.CAPS + [capabilities.CAP_ROSTER, capabilities.CAP_ROSTER_V2, *caps_extra]
    pack = make_pack(tmp_path, {}, {"a": v2, "b": v2, "c": ss.CAPS + [capabilities.CAP_ROSTER], "d": v2})
    pack_caps = {IDS[n]: pack[n]._connected() for n in "abcd"}
    links = {"a": "bc", "b": "ad", "c": "a", "d": "b"}
    to_c = []

    def only(name):
        def connected():
            out = []
            for peer, post, caps in pack_caps[IDS[name]]:
                if peer not in [IDS[x] for x in links[name]]:
                    continue
                if peer == IDS["c"] and name == "a":
                    def tap(method, path, body, _p=post):
                        to_c.append(json.loads(json.dumps(body)))
                        return _p(method, path, body)
                    out.append((peer, tap, caps))
                else:
                    out.append((peer, post, ss.CAPS + [capabilities.CAP_ROSTER] if name == "c" else caps))
            return out
        return connected
    for n in "abcd":
        pack[n]._connected = only(n)
    return pack, to_c


def _computers(count: int):
    rows = _inputs(("a", "b", "c", "d"))
    return rows + _many(count)[4:] if count > 4 else rows


def _settle(pack, rounds=4):
    mesh(pack, rounds)


def test_v2_list_is_issued_pieced_reassembled_and_forgeries_refused(monkeypatch, tmp_path):
    pack, to_c = _four(monkeypatch, tmp_path)
    a, b, c, d = (pack[n] for n in "abcd")
    _settle(pack, 2)
    assert a.refresh_roster(_computers(4)) == "bump:first"
    assert a.custody.roster() is not None and a.custody.roster_v2().generation == a.custody.roster().generation
    _settle(pack)
    assert a.refresh_roster(_computers(20)) == "bump:membership"
    v1 = a.custody.roster()
    assert len(v1.computers) == 4 and len(a.custody.roster_v2().computers) == 20 and v1.generation == a.custody.roster_v2().generation
    wire = a.custody.roster_v2_wire()
    assert len(roster_v2.blob(wire)) > roster_pieces.PIECE_BYTES
    _settle(pack, 6)
    for n in "bd":
        assert pack[n].custody.roster_v2_wire() == wire
        parsed, sig = roster_v2.from_wire_v2(pack[n].custody.roster_v2_wire())
        assert roster_v2.verify_v2(parsed, sig, ss.PUB[IDS["a"]]) and len(parsed.computers) == 20
        assert parsed.entry(IDS["b"]).mesh and parsed.entry(IDS["b"]).capabilities and parsed.entry(IDS["c"]).mesh is True
    assert c.custody.roster_v2() is None and to_c and all("roster_v2" not in body for body in to_c)
    held = d.custody.roster_v2()
    forged = roster_v2.RosterV2(**{**held.model_dump(), "generation": held.generation + 5, "issued_at": held.issued_at + 9})
    sig_b = roster_v2.sign_v2(forged, ss.KEYS["b"], IDS["b"])
    verdict = roster_v2.judge_v2(held=held, remote=forged, signature=sig_b, held_alpha=IDS["a"], public_key_for=lambda i: ss.PUB.get(i))
    assert verdict.outcome == settings_sign.REFUSE_NOT_ALPHA
    forged_wire = roster_v2.to_wire_v2(forged, sig_b.to_dict())
    assert d.custody.merge_roster_v2(forged_wire, IDS["b"]) is False
    taken = []
    far = roster_v2.RosterV2(**{**held.model_dump(), "generation": held.generation + 9, "issued_at": held.issued_at + 9})
    far_wire = roster_v2.to_wire_v2(far, roster_v2.sign_v2(far, ss.KEYS["a"], IDS["a"]).to_dict())
    sender = roster_pieces.Courier(lambda: far_wire, lambda w, s: False)
    part0 = sender.outgoing("x", None)
    assert part0["piece"]["index"] == 0 and part0["piece"]["count"] == 2
    bad_sha = {**part0, "piece": {**part0["piece"], "sha256": "0" * 64}}
    taker = roster_pieces.Courier(lambda: None, lambda w, s: taken.append(w) or True)
    assert taker.incoming("x", bad_sha) is False
    out_of_order = {**part0, "piece": {**part0["piece"], "index": 1}}
    assert taker.incoming("x", out_of_order) is False
    assert taker.incoming("x", part0) is False
    want = taker.outgoing("x", None)["want"]
    assert want == {"sha256": part0["head"]["sha256"], "index": 1}
    part1 = sender.outgoing("x", {"head": None, "want": want})
    assert part1["piece"]["index"] == 1
    data = bytearray(part1["piece"]["data"].encode())
    data[10:12] = b"AB" if data[10:12] != b"AB" else b"CD"
    assert taker.incoming("x", {**part1, "piece": {**part1["piece"], "data": data.decode()}}) is False
    assert taken == [] and part1["head"]["sha256"] in taker._rejected
    assert taker.incoming("x", part0) is False and taker.incoming("x", part1) is False
    assert taken == []
    v1 = c.custody.roster()
    assert v1 is not None and v1.generation > 0
    old = roster_v2.RosterV2(**{**held.model_dump(), "generation": v1.generation - 1})
    old_wire = roster_v2.to_wire_v2(old, roster_v2.sign_v2(old, ss.KEYS["a"], IDS["a"]).to_dict())
    assert c.custody.merge_roster_v2(old_wire, IDS["a"]) is False and c.custody.roster_v2() is None


def test_the_65th_computer_is_refused_in_words_with_the_switch_on(monkeypatch, tmp_path):
    pack, _ = _four(monkeypatch, tmp_path)
    a = pack["a"]
    mesh(pack, 2)
    assert a.refresh_roster(_computers(64)) == "bump:first"
    assert len(a.custody.roster_v2().computers) == 64 and len(a.custody.roster().computers) <= 16 if a.custody.roster() else True
    held = a.custody.roster_v2_wire()
    assert a.refresh_roster(_computers(65)) == ""
    assert a.custody.roster_v2_wire() == held
    assert a.view([])["roster_refusal"] == {"code": "pack_full", "count": 65, "limit": 64}
    with pytest.raises(roster_doc.RosterFull) as full:
        a.refresh_roster(_computers(65), eligible={IDS["b"]: True})
    assert str(full.value) == "the pack is full: 65 computers, the limit is 64"


def test_join_gate_refuses_a_new_computer_when_the_pack_is_full(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    conn = sqlite3.connect(tmp_path / "t.db", isolation_level=None)
    apply_computer_links(conn)
    store.CACHE.replace([])
    try:
        for i in range(14):
            store.put(conn, store.LinkRow(f"m{i}", updated_at="", role="member", transport="tls", link_fid=f"f{i}", cert_sha256=f"s{i}"))
        commit.check_room(conn, "new")
        store.put(conn, store.LinkRow("m14", updated_at="", role="member", transport="tls", link_fid="f14", cert_sha256="s14"))
        commit.check_room(conn, "m3")
        with pytest.raises(commit.JoinRefused) as refused:
            commit.check_room(conn, "new")
        assert refused.value.code == "pack_full" and "the pack is full: 16 computers" in str(refused.value)
    finally:
        conn.close()


def _part(gen: int, sha: str, index: int, count: int, data: bytes = b"x" * 10):
    import base64
    return {"head": {"generation": gen, "issued_at": 1, "sha256": sha}, "want": None,
            "piece": {"sha256": sha, "index": index, "count": count, "data": base64.b64encode(data).decode()}}


def test_a_stalled_assembly_cannot_jam_the_courier(monkeypatch):
    courier = roster_pieces.Courier(lambda: None, lambda w, s: False)
    courier.incoming("evil", _part(2 ** 62, "a" * 64, 0, 96))
    assert courier._asm is not None
    courier.incoming("real", _part(5, "b" * 64, 0, 2))
    assert courier._asm["head"][2] == "a" * 64
    later = roster_pieces.time.monotonic() + roster_pieces.STALL_SECONDS + 1
    monkeypatch.setattr(roster_pieces.time, "monotonic", lambda: later)
    courier.incoming("real", _part(5, "b" * 64, 0, 2))
    assert courier._asm["head"][2] == "b" * 64


def test_with_capabilities_keeps_only_valid_names():
    rows = _many(2)
    out = roster_v2.with_capabilities(rows, "iid-000", [], lambda iid: ["ok.name", "", "x" * 65, "bad\x00", 3])
    assert out[1].capabilities == ("ok.name",)
    roster_v2.plan_v2(None, out, alpha=out[0].install_id)

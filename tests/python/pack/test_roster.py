
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401, E402
from fastapi import HTTPException  # noqa: E402

from src.api import pack_machines_routes  # noqa: E402
from src.core.computers import store  # noqa: E402
from src.core.computers.member_listener import Rendezvous  # noqa: E402
from src.core.computers.member_relay_dial import MemberRelayDialer  # noqa: E402
from src.core.pack.machines import capabilities, roster_doc, settings_sign  # noqa: E402
from tests.python.computers.test_tls_link import MAIN_IID, world  # noqa: E402, F401
from tests.python.pack.test_settings_signing import CAPS, IDS, KEYS, PUB, make_pack, mesh  # noqa: E402

ROSTER_CAPS = CAPS + [capabilities.CAP_ROSTER]


def _inputs(names=("a", "b", "c"), **over):
    rows = []
    for i, n in enumerate(names):
        row = dict(install_id=IDS[n], label=n, fed_public_key=PUB[IDS[n]], cert=bytes([i + 1]) * 40, next_cert=None,
                   addresses=(f"10.0.0.{i + 1}",), link_port=47110, relay_id=None)
        row.update(over.get(n, {}))
        rows.append(roster_doc.RosterInput(**row))
    return rows


def _setup(tmp_path, caps=None):
    pack = make_pack(tmp_path, {}, caps)
    mesh(pack)
    return pack


def test_alpha_issues_bumps_and_every_roster_computer_takes_it(tmp_path):
    pack = _setup(tmp_path, {n: ROSTER_CAPS for n in IDS})
    a = pack["a"]
    assert a.refresh_roster(_inputs()) == "bump:first"
    first = a.custody.roster()
    assert [c.install_id for c in first.computers][0] in IDS.values() and not any(c.takeover_eligible for c in first.computers)
    assert roster_doc.verify(first, a.state.stored_roster()[1], PUB[IDS["a"]])
    mesh(pack)
    assert all(pack[n].custody.roster() is not None and pack[n].custody.roster().generation == first.generation for n in "bc")
    moved = _inputs(b={"addresses": ("10.9.9.9",)})
    assert a.refresh_roster(moved) == ""
    a.custody._clock = lambda: first.issued_at + 301
    assert a.refresh_roster(moved) == "hint"
    assert a.custody.roster().generation == first.generation and a.custody.roster().issued_at > first.issued_at
    assert a.refresh_roster(_inputs(), eligible={IDS["b"]: True}) == "bump:eligibility"
    order = [IDS["c"], IDS["b"], IDS["a"]]
    assert a.refresh_roster(_inputs(), order=order) == "bump:order"
    mesh(pack)
    assert pack["c"].custody.roster().order() == order and pack["c"].custody.roster().entry(IDS["b"]).takeover_eligible
    with pytest.raises(ValueError):
        a.refresh_roster(_inputs(), eligible={"nobody": True})
    assert pack["b"].refresh_roster(_inputs()) == ""


def test_roster_from_a_non_alpha_or_older_or_restructured_is_refused(tmp_path):
    pack = _setup(tmp_path, {n: ROSTER_CAPS for n in IDS})
    pack["a"].refresh_roster(_inputs())
    mesh(pack)
    held = pack["b"].custody.roster()
    key_for = lambda iid: PUB.get(iid)  # noqa: E731
    forged = roster_doc.Roster(**{**held.model_dump(), "generation": held.generation + 5, "issued_at": held.issued_at + 9})
    sig_c = roster_doc.sign(forged, KEYS["c"], IDS["c"])
    assert roster_doc.judge(held=held, remote=forged, signature=sig_c, held_alpha=IDS["a"], public_key_for=key_for).outcome == settings_sign.REFUSE_NOT_ALPHA
    sig_a = roster_doc.sign(forged, KEYS["a"], IDS["a"])
    assert roster_doc.judge(held=held, remote=forged, signature=sig_a, held_alpha=IDS["a"], public_key_for=key_for).outcome == settings_sign.ACCEPT
    older = roster_doc.Roster(**{**held.model_dump(), "issued_at": held.issued_at - 1})
    assert roster_doc.judge(held=held, remote=older, signature=roster_doc.sign(older, KEYS["a"], IDS["a"]), held_alpha=IDS["a"],
                            public_key_for=key_for).outcome == settings_sign.IGNORE
    flipped = [dict(c.model_dump(), takeover_eligible=True) if c.install_id == IDS["c"] else c.model_dump() for c in held.computers]
    same_gen = roster_doc.Roster(**{**held.model_dump(), "computers": flipped, "issued_at": held.issued_at + 9})
    verdict = roster_doc.judge(held=held, remote=same_gen, signature=roster_doc.sign(same_gen, KEYS["a"], IDS["a"]),
                               held_alpha=IDS["a"], public_key_for=key_for)
    assert verdict.outcome == settings_sign.REFUSE_MALFORMED and verdict.reason == roster_doc.REASON_SAME_GENERATION
    assert roster_doc.judge(held=held, remote=forged, signature=None, held_alpha=IDS["a"], public_key_for=key_for).outcome == settings_sign.REFUSE_UNSIGNED


def test_the_former_alpha_can_only_hand_over_to_the_settings_master_at_or_below_its_counter(tmp_path):
    pack = _setup(tmp_path, {n: ROSTER_CAPS for n in IDS})
    pack["a"].refresh_roster(_inputs())
    mesh(pack)
    held = pack["b"].custody.roster()
    key_for = lambda iid: PUB.get(iid)  # noqa: E731

    def verdict(alpha, generation):
        remote = roster_doc.Roster(**{**held.model_dump(), "alpha": IDS[alpha], "generation": generation, "issued_at": held.issued_at + 9})
        return roster_doc.judge(held=held, remote=remote, signature=roster_doc.sign(remote, KEYS["a"], IDS["a"]), held_alpha=IDS["b"],
                                held_roster_alpha=IDS["a"], held_generation=held.generation + 1, public_key_for=key_for).outcome
    assert verdict("b", held.generation + 1) == settings_sign.ACCEPT
    assert verdict("c", held.generation + 1) == settings_sign.REFUSE_NOT_ALPHA
    assert verdict("b", 10 ** 9) == settings_sign.REFUSE_NOT_ALPHA


def test_a_peer_without_the_capability_gets_no_roster_and_a_handover_reaches_everyone(tmp_path):
    caps = {"a": ROSTER_CAPS, "b": ROSTER_CAPS, "c": CAPS}
    pack = _setup(tmp_path, caps)
    sent: list = []
    inner = pack["a"]._connected

    def spy():
        for peer, post, pcaps in inner():
            async def tap(method, path, body, _post=post, _peer=peer):
                sent.append((_peer, "roster" in body))
                return await _post(method, path, body)
            yield peer, tap, pcaps
    pack["a"]._connected = spy
    c_inner = pack["c"]._connected
    pack["c"]._connected = lambda: [(peer, post, CAPS) for peer, post, _caps in c_inner()]
    pack["a"].refresh_roster(_inputs())
    mesh(pack)
    assert (IDS["b"], True) in sent and (IDS["c"], False) in sent and (IDS["c"], True) not in sent
    assert pack["c"].custody.roster() is None and pack["b"].custody.roster() is not None
    pack["a"].edit_settings({"master_install_id": IDS["b"]})
    mesh(pack)
    assert pack["b"].custody.roster().alpha == IDS["b"] and pack["a"].custody.roster().alpha == IDS["b"]


def _route_world(pack, caps_for_peer):
    rt = pack["a"]
    wired = SimpleNamespace(runtime=rt, peers=lambda: [SimpleNamespace(install_id=IDS[n], label=n, capabilities=caps_for_peer[n]) for n in "bc"])
    rt.resolve = lambda name, peers: IDS.get(name) or (IDS[name[0]] if name in "abc" else None)
    rt.view = lambda peers: {}
    rt.kick = lambda: None

    class Rt:
        async def roster_inputs(self):
            return _inputs()

        async def after_roster_change(self):
            return None
    return wired, Rt()


def test_eligibility_on_needs_the_capability_and_alpha(tmp_path, monkeypatch):
    pack = _setup(tmp_path, {n: ROSTER_CAPS for n in IDS})
    pack["a"].refresh_roster(_inputs())
    wired, rt = _route_world(pack, {"b": ROSTER_CAPS, "c": CAPS})
    monkeypatch.setattr(pack_machines_routes, "_wired", lambda: wired)
    monkeypatch.setattr(pack_machines_routes.computers_runtime, "active", lambda: rt)
    body = lambda machine, on: pack_machines_routes.EligibleBody(machine=machine, eligible=on)  # noqa: E731
    with pytest.raises(HTTPException) as err:
        asyncio.run(pack_machines_routes.put_eligible(body("c", True), None))
    assert err.value.status_code == 409 and err.value.detail["code"] == "update_required"
    out = asyncio.run(pack_machines_routes.put_eligible(body("b", True), None))
    assert IDS["b"] in out["eligible"] and out["changed"] == "bump:eligibility"
    out = asyncio.run(pack_machines_routes.put_successors(pack_machines_routes.SuccessorsBody(order=["c", "b", "a"]), None))
    assert out["order"] == [IDS["c"], IDS["b"], IDS["a"]]
    pack["b"].edit_settings({})
    pack["b"].resolve = wired.runtime.resolve
    wired_b = SimpleNamespace(runtime=pack["b"], peers=wired.peers)
    monkeypatch.setattr(pack_machines_routes, "_wired", lambda: wired_b)
    with pytest.raises(HTTPException) as err:
        asyncio.run(pack_machines_routes.put_successors(pack_machines_routes.SuccessorsBody(order=["c", "b", "a"]), None))
    assert err.value.status_code == 409 and err.value.detail["code"] == "not_alpha"


def test_the_hello_roster_is_cut_to_the_budget_and_the_relay_dial_is_tight(world):
    big = {"roster": {"roster": {"x": "y" * (roster_doc.HELLO_ROSTER_BUDGET + 10)}, "sig": {}}, "relay_id": "abc234"}
    assert "roster" not in roster_doc.fit_hello(big) and roster_doc.fit_hello(big)["relay_id"] == "abc234"
    _root, _dirs, idents = world
    cert = idents["main"].cert
    row = store.LinkRow(MAIN_IID, "main", "tls", "", cert_der=cert.der, cert_sha256=cert.cert_sha256, link_fid=cert.link_fid)

    async def attempt(listed):
        offered: list = []
        rv = SimpleNamespace(offer=lambda r, w, via_relay=False: offered.append(w))
        closed: list = []

        class W:
            def get_extra_info(self, _name):
                return SimpleNamespace(getpeercert=lambda binary_form=True: cert.der)

            def close(self):
                closed.append(1)

        async def connect(host, ctx):
            return object(), W()
        d = MemberRelayDialer(identity=idents["member"], rendezvous=rv, main=lambda: row, relay_host=lambda: "h", enabled=lambda: True,
                              linked=lambda: False, connect=connect, unlinked_after=0.0, roster_shas=lambda _iid: listed)
        await d._dial("h", row)
        return bool(offered), bool(closed)
    assert asyncio.run(attempt(None)) == (True, False)
    assert asyncio.run(attempt(frozenset({cert.cert_sha256}))) == (True, False)
    assert asyncio.run(attempt(frozenset({"0" * 64}))) == (False, True)


from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401, E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from src.core.computers import alpha_rows, store  # noqa: E402
from src.core.computers.ddl import apply_computer_links  # noqa: E402
from src.core.computers.tls_identity import build_cert_der, link_fid_for, _raw_pub  # noqa: E402
from src.core.pack.machines import capabilities, roster_doc, roster_v2  # noqa: E402
from tests.python.pack import test_settings_signing as ss  # noqa: E402
from tests.python.pack.test_settings_signing import CAPS, IDS, make_pack, mesh  # noqa: E402

A, C = IDS["a"], IDS["c"]
V2_CAPS = CAPS + [capabilities.CAP_ROSTER, capabilities.CAP_ROSTER_V2, capabilities.CAP_MESH]


def _key(i: int) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes([i + 1]) * 32)


def _computers(count: int, caps=tuple(V2_CAPS)):
    rows = []
    for i in range(count):
        iid = list(IDS.values())[i] if i < 3 else f"iid-{i:03d}"
        fed = ss.PUB[iid] if i < 3 else ss.PUB[A]
        rows.append(roster_doc.RosterInput(install_id=iid, label=f"c{i}", fed_public_key=fed, cert=build_cert_der(_key(i)), next_cert=None,
                                           addresses=(f"10.0.0.{i + 1}",), link_port=47110, relay_id=None, capabilities=caps))
    return rows


def _world(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    pack = make_pack(tmp_path, {}, {n: V2_CAPS for n in IDS})
    inputs = _computers(18)
    mesh(pack)
    assert pack["a"].refresh_roster(inputs[:3]) == "bump:first"
    mesh(pack)
    assert pack["a"].refresh_roster(inputs, eligible={C: True}).startswith("bump:")
    mesh(pack, 4)
    return pack, inputs


def test_eligible_computer_claims_and_its_v2_list_names_it_alpha(monkeypatch, tmp_path):
    pack, inputs = _world(monkeypatch, tmp_path)
    c = pack["c"]
    assert len(c.custody.roster().computers) == 3 and len(c.custody.roster_v2().computers) == 18
    lists = c.custody.held_lists()
    assert isinstance(lists[0], roster_v2.RosterV2) and lists[1] is not None
    c.custody.takeover_on = lambda: True
    assert c.custody.claim() is True
    doc = c.custody.settings()
    held, sig = c.state.stored_roster_v2()
    assert held.alpha == C and held.generation == doc.rev[0] == c.custody.roster().generation
    assert sig is not None and sig.signer == C and roster_v2.verify_v2(held, sig, ss.PUB[C])
    assert len(held.computers) == 18
    conn = sqlite3.connect(tmp_path / "rows.db", isolation_level=None)
    apply_computer_links(conn)
    store.CACHE.replace([])
    try:
        own_fid = link_fid_for(_raw_pub(_key(2).public_key()))
        written = alpha_rows.rewrite_rows(conn, own_iid=C, own_link_fid=own_fid, own_link_port=47110, roster=c.custody.held_lists()[0], new_alpha=C)
        assert written == 17 and {r.role for r in store.list_rows(conn)} == {"member"} and len(store.list_rows(conn)) == 17
    finally:
        conn.close()
        store.CACHE.replace([])


def test_an_eligible_mark_outside_the_v1_list_is_refused(monkeypatch, tmp_path):
    pack, inputs = _world(monkeypatch, tmp_path)
    with pytest.raises(roster_doc.RosterRefused):
        pack["a"].refresh_roster(inputs, eligible={inputs[10].install_id: True})


def test_switch_off_held_lists_is_todays_v1_pair(tmp_path, monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert capabilities.mesh_on() is False
    pack = make_pack(tmp_path, {}, {n: CAPS + [capabilities.CAP_ROSTER] for n in IDS})
    mesh(pack)
    inputs = _computers(3, caps=())
    assert pack["a"].custody.held_lists() is None
    assert pack["a"].refresh_roster(inputs) == "bump:first"
    held = pack["a"].custody.held_lists()
    assert held == (pack["a"].custody.roster(), pack["a"].custody.roster_wire()) and isinstance(held[0], roster_doc.Roster)
    assert pack["a"].state.stored_roster_v2() is None


def test_a_v2_list_older_than_the_held_v1_is_ignored_and_never_re_signed(monkeypatch, tmp_path):
    pack, inputs = _world(monkeypatch, tmp_path)
    c = pack["c"]
    v1 = c.custody.roster()
    stale, sig = c.state.stored_roster_v2()
    c.state.save_roster_v2(roster_v2.to_wire_v2(roster_v2.RosterV2(**{**stale.model_dump(), "generation": v1.generation - 1}), sig.to_dict()))
    held = c.custody.held_lists()
    assert isinstance(held[0], roster_doc.Roster)
    c.custody.takeover_on = lambda: True
    assert c.custody.claim() is True
    assert c.state.stored_roster_v2() is None


def test_a_held_v2_is_ignored_when_the_switch_is_off(monkeypatch, tmp_path):
    pack, inputs = _world(monkeypatch, tmp_path)
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert isinstance(pack["c"].custody.held_lists()[0], roster_doc.Roster)


def _adopt_claim(pack, b_name="b"):
    from src.core.pack.machines import settings_sign

    c = pack["c"]
    c.custody.takeover_on = lambda: True
    assert c.custody.claim() is True
    cc = c.custody
    roster, rsig = roster_doc.from_wire(cc.roster_wire())
    assert pack[b_name].custody.adopt_alpha(cc.settings(), settings_sign.signature_from(cc.state.settings_signature()), roster, rsig,
                                            settings_sign.CLAIM, C)
    return cc.roster_v2_wire()


def test_an_interim_claimants_v2_list_is_refused_when_the_held_v2_lags_the_home(monkeypatch, tmp_path):
    pack, inputs = _world(monkeypatch, tmp_path)
    b = pack["b"]
    stale, sig = b.state.stored_roster_v2()
    lag = roster_v2.RosterV2(**{**stale.model_dump(), "generation": stale.generation - 1})
    b.state.save_roster_v2(roster_v2.to_wire_v2(lag, sig.to_dict()))
    claimant_wire = _adopt_claim(pack)
    assert b.custody.interim()
    assert b.state.stored_roster_v2() is None
    assert b.custody.merge_roster_v2(claimant_wire, C) is False
    b.state.save_roster_v2(roster_v2.to_wire_v2(stale, sig.to_dict()))
    assert b.custody.merge_roster_v2(claimant_wire, C) is True


def test_a_benign_takeover_v2_is_taken_after_settings_edits_moved_the_counter(monkeypatch, tmp_path):
    pack, inputs = _world(monkeypatch, tmp_path)
    assert pack["a"].custody.mint({"placement_mode": "enhanced"}, strict=True)
    mesh(pack)
    b = pack["b"]
    assert b.custody.home_state().last_home[0] > b.custody.roster_v2().generation
    claimant_wire = _adopt_claim(pack)
    assert b.state.stored_roster_v2() is not None
    assert b.custody.merge_roster_v2(claimant_wire, C) is True


def _off_at_a_and_b(pack, inputs):
    x = inputs[3].install_id
    assert pack["a"].refresh_roster(inputs, link_peers={x: False}) == "bump:authority"
    a, b = pack["a"].custody, pack["b"].custody
    assert b.merge(*a.outgoing(), A, a.roster_wire()) and b.merge_roster(a.roster_wire(), A) and b.merge_roster_v2(a.roster_v2_wire(), A)
    assert b.roster_v2().entry(x).link_peers is False
    return x


def test_a_stale_successor_cannot_turn_a_switched_off_computer_back_on(monkeypatch, tmp_path):
    from structlog.testing import capture_logs

    from src.core.pack.machines import settings_sign

    pack, inputs = _world(monkeypatch, tmp_path)
    x = _off_at_a_and_b(pack, inputs)
    b, c = pack["b"].custody, pack["c"]
    assert c.custody.roster_v2().entry(x).link_peers is True
    c.custody.takeover_on = lambda: True
    assert c.custody.claim() and c.custody.confirm_local()
    assert pack["c"].refresh_roster(inputs, eligible={IDS["b"]: True}).startswith("bump:")
    on_wire = c.custody.roster_v2_wire()
    assert c.custody.roster_v2().entry(x).link_peers is True
    roster, rsig = roster_doc.from_wire(c.custody.roster_wire())
    assert b.adopt_alpha(c.custody.settings(), settings_sign.signature_from(c.state.settings_signature()), roster, rsig, settings_sign.CLAIM, C)
    assert b.confirm_local() and not b.interim()
    with capture_logs() as logs:
        assert b.merge_roster_v2(on_wire, C) is False
    assert [e for e in logs if e["event"] == "pack_roster_v2_refused" and e.get("outcome") == "switch_older"]
    assert b.roster_v2().entry(x).link_peers is False
    assert c.custody.refresh_roster(inputs, link_peers={x: True}) == "bump:authority"
    assert b.merge_roster_v2(c.custody.roster_v2_wire(), C) is True and b.roster_v2().entry(x).link_peers is True

    (tmp_path / "chain").mkdir()
    pack2, inputs2 = _world(monkeypatch, tmp_path / "chain")
    _off_at_a_and_b(pack2, inputs2)
    c2 = pack2["c"].custody
    c2.takeover_on = lambda: True
    assert c2.claim()
    a2 = pack2["a"].custody
    assert c2.merge(*a2.outgoing(), IDS["b"], a2.roster_wire())
    assert c2.claim()
    assert c2.state.stored_roster_v2() is None


def test_a_member_that_was_away_for_a_remove_and_re_add_refuses_the_re_added_computer_on(monkeypatch, tmp_path):
    pack, inputs = _world(monkeypatch, tmp_path)
    x = _off_at_a_and_b(pack, inputs)
    a, b = pack["a"], pack["b"].custody
    others = [i for i in inputs if i.install_id != x]
    assert a.refresh_roster(others).startswith("bump:")
    assert a.refresh_roster(inputs).startswith("bump:")
    assert a.custody.roster_v2().entry(x).link_peers is True and a.custody.roster_v2().entry(x).link_at == 0
    assert b.merge_roster_v2(a.custody.roster_v2_wire(), A) is False
    assert a.refresh_roster(inputs, link_peers={x: True}) == "bump:authority"
    assert a.custody.roster_v2().entry(x).link_at == a.custody.roster_v2().generation
    assert b.merge_roster_v2(a.custody.roster_v2_wire(), A) is True


def test_a_refused_switch_older_list_is_shown_with_signer_and_computers_until_the_signer_merges(monkeypatch, tmp_path):
    from src.core.pack.machines import settings_sign

    pack, inputs = _world(monkeypatch, tmp_path)
    x = _off_at_a_and_b(pack, inputs)
    b, c = pack["b"].custody, pack["c"]
    pushed = []
    b.switch_refusal_changed = lambda: pushed.append(1)
    assert "link_switch_refused" not in pack["b"].view([])
    c.custody.takeover_on = lambda: True
    assert c.custody.claim() and c.custody.confirm_local()
    assert pack["c"].refresh_roster(inputs, eligible={IDS["b"]: True}).startswith("bump:")
    on_wire = c.custody.roster_v2_wire()
    roster, rsig = roster_doc.from_wire(c.custody.roster_wire())
    assert b.adopt_alpha(c.custody.settings(), settings_sign.signature_from(c.state.settings_signature()), roster, rsig, settings_sign.CLAIM, C)
    assert b.confirm_local()
    assert b.merge_roster_v2(on_wire, C) is False
    assert pack["b"].view([])["link_switch_refused"] == {"signer": C, "computers": [x]} and pushed == [1]
    assert b.merge_roster_v2(on_wire, C) is False and pushed == [1]
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert "link_switch_refused" not in pack["b"].view([])
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    assert c.custody.refresh_roster(inputs, link_peers={x: True}) == "bump:authority"
    b._set_switch_refusal({"signer": "iid-earlier-alpha", "computers": [x]})
    assert b.merge_roster_v2(c.custody.roster_v2_wire(), C) is True
    assert "link_switch_refused" not in pack["b"].view([]) and pushed == [1, 1, 1]


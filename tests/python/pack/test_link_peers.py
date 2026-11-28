
from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401, E402
from fastapi import HTTPException  # noqa: E402

from src.api import pack_link_peers_routes as routes, pack_machines_routes  # noqa: E402
from src.core.computers import mesh_choice  # noqa: E402
from src.core.federation import mesh_grants  # noqa: E402
from src.core.pack.machines import capabilities, roster_v2, settings_custody, settings_sign  # noqa: E402
from src.core.pack.machines.config_state import ConfigState, LINK_SWITCHES_KEY, ROSTER_V2_KEY  # noqa: E402
from src.core.pack.machines.restrictions import Restrictions  # noqa: E402
from tests.python.pack import test_roster_v2 as t2  # noqa: E402
from tests.python.pack import test_settings_signing as ss  # noqa: E402

IDS = ss.IDS


def _wired(rt, peers_of):
    names = {IDS[n]: n for n in "abcd"}
    rt.resolve = lambda name, peers: name if name in names else (IDS[name] if name in IDS else None)
    rt.kick = lambda: None
    return SimpleNamespace(runtime=rt, peers=lambda: [SimpleNamespace(install_id=IDS[n], label=n, capabilities=[]) for n in peers_of])


def _put(wired, machine, on):
    return asyncio.run(routes.put_link_peers(routes.LinkPeersBody(machine=machine, on=on)))


def _code(call):
    with pytest.raises(HTTPException) as err:
        call()
    detail = err.value.detail
    return err.value.status_code, detail.get("code") if isinstance(detail, dict) else detail


def _inputs():
    return [dataclasses.replace(i, capabilities=(capabilities.CAP_MESH,)) for i in t2._computers(4)]


def _grant(d, b):
    lst = d.custody.roster_v2()
    return mesh_grants.derive(lst, self_iid=IDS["d"], peer_iid=IDS["b"], cert_sha=lst.entry(IDS["b"]).shas()[0], restrictions=Restrictions(), has_replica=False)


def test_link_switch_route_sets_the_signed_list_and_members_enforce_it(monkeypatch, tmp_path):
    pack, _ = t2._four(monkeypatch, tmp_path, caps_extra=(capabilities.CAP_MESH,))
    a, b, d = pack["a"], pack["b"], pack["d"]
    t2._settle(pack, 2)
    assert a.refresh_roster(_inputs()) == "bump:first"
    t2._settle(pack)
    old = a.custody.roster_v2_wire()
    wired_a, wired_b = _wired(a, "bcd"), _wired(b, "acd")

    class Rt:
        async def roster_inputs(self):
            return _inputs()

        async def after_roster_change(self):
            return None
    monkeypatch.setattr(pack_machines_routes, "_wired", lambda: wired_a)
    monkeypatch.setattr(pack_machines_routes.computers_runtime, "active", lambda: Rt())
    assert IDS["b"] in mesh_choice.eligible_ids(d.custody.roster_v2(), IDS["d"]) and _grant(d, b) is not None

    out = _put(wired_a, "b", False)
    assert out["changed"] == "bump:authority" and out["on"] is False and out["machine"] == IDS["b"]
    t2._settle(pack)
    for n in "abd":
        assert pack[n].custody.roster_v2().entry(IDS["b"]).link_peers is False
    assert mesh_choice.own_switch(b.custody.roster_v2(), IDS["b"]) == "off"
    assert IDS["b"] not in mesh_choice.eligible_ids(d.custody.roster_v2(), IDS["d"]) and _grant(d, b) is None

    monkeypatch.setattr(pack_machines_routes, "_wired", lambda: wired_b)
    assert _code(lambda: _put(wired_b, "b", True)) == (409, "link_peers_not_alpha")
    monkeypatch.setattr(pack_machines_routes, "_wired", lambda: wired_a)

    held = d.custody.roster_v2()
    mine = roster_v2.RosterV2(**{**held.model_dump(), "generation": held.generation + 1, "issued_at": held.issued_at + 1,
                                 "computers": [{**c.model_dump(), "link_peers": True} if c.install_id == IDS["b"] else c.model_dump() for c in held.computers]})
    wire = roster_v2.to_wire_v2(mine, roster_v2.sign_v2(mine, ss.KEYS["b"], IDS["b"]).to_dict())
    verdicts = []
    real_judge = roster_v2.judge_v2

    def spy(**kwargs):
        verdicts.append(real_judge(**kwargs))
        return verdicts[-1]
    monkeypatch.setattr(roster_v2, "judge_v2", spy)
    assert d.custody.merge_roster_v2(wire, IDS["b"]) is False
    assert d.custody.merge_roster_v2(old, IDS["a"]) is False
    assert [(v.outcome, v.reason) for v in verdicts] == [(settings_sign.REFUSE_NOT_ALPHA, "signer is not the alpha held here"),
                                                         (settings_sign.IGNORE, settings_sign.REASON_NOT_NEWER)]
    monkeypatch.setattr(roster_v2, "judge_v2", real_judge)
    assert d.custody.roster_v2().entry(IDS["b"]).link_peers is False

    generation = a.custody.roster_v2().generation
    with monkeypatch.context() as frozen:
        frozen.setattr(a.custody, "interim", lambda: True)
        frozen_code = _code(lambda: _put(wired_a, "b", True))
    assert frozen_code == (409, "link_peers_frozen") and a.custody.roster_v2().generation == generation
    assert _code(lambda: _put(wired_a, "a", True)) == (422, "link_peers_alpha")
    assert _code(lambda: _put(wired_a, "nobody", True))[0] == 404

    assert _put(wired_a, "b", True)["on"] is True
    t2._settle(pack)
    assert IDS["b"] in mesh_choice.eligible_ids(d.custody.roster_v2(), IDS["d"]) and _grant(d, b) is not None

    owner = lambda **scope: SimpleNamespace(scope=scope)  # noqa: E731
    assert _code(lambda: asyncio.run(routes._owner_login(owner(mesh_peer=True), True, None))) == (403, "link_peers_owner_only")
    assert _code(lambda: asyncio.run(routes._owner_login(owner(via_peer_link=True), True, None))) == (403, "link_peers_owner_only")
    monkeypatch.setattr(routes, "is_api_key", lambda token: True)
    assert _code(lambda: asyncio.run(routes._owner_login(owner(), True, SimpleNamespace(credentials="cak_x")))) == (403, "link_peers_owner_only")

    monkeypatch.setattr(pack_machines_routes.computers_runtime, "active", lambda: None)
    view = {"master_install_id": IDS["a"], "machines": [{"install_id": IDS["b"], "is_self": False, "state": "connected"}]}
    assert pack_machines_routes._reconnect_fields(wired_a, view)["machines"][0]["link_peers"] is True
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    off = pack_machines_routes._reconnect_fields(wired_a, {"master_install_id": IDS["a"], "machines": [{"install_id": IDS["b"], "is_self": False, "state": "connected"}]})
    assert "link_peers" not in off["machines"][0] and "mesh_capable" not in off["machines"][0]
    assert _code(lambda: asyncio.run(routes._mesh_route())) == (404, "Not Found")


def test_the_link_switch_fails_closed_across_a_lost_corrupt_or_lagging_list(monkeypatch, tmp_path):
    pack, _ = t2._four(monkeypatch, tmp_path, caps_extra=(capabilities.CAP_MESH,))
    a, b, d = pack["a"], pack["b"], pack["d"]
    t2._settle(pack, 2)
    assert a.refresh_roster(_inputs()) == "bump:first"
    t2._settle(pack)
    first = a.custody.roster_v2_wire()
    assert a.refresh_roster(_inputs(), link_peers={IDS["b"]: False}) == "bump:authority"
    t2._settle(pack)
    assert d.custody.state.link_switches()[0] == "ok" and a.custody.state.link_switches()[2][IDS["b"]] is False

    a.state._commit_many({ROSTER_V2_KEY: None})
    a.refresh_roster(_inputs())
    assert a.custody.roster_v2().entry(IDS["b"]).link_peers is False and not a.custody.link_switches_unknown

    a.state._commit_many({ROSTER_V2_KEY: {"junk": 1}, LINK_SWITCHES_KEY: "junk"})
    assert a.state.link_switches()[0] == "corrupt"
    assert a.refresh_roster(_inputs()) == "" and a.state.stored_roster_v2() is None
    assert a.custody.link_switches_unknown and a.view([]).get("link_switches_unknown") is True
    assert a.refresh_roster(_inputs(), link_peers={IDS["d"]: True}) == "bump:first"
    issued = a.custody.roster_v2()
    assert issued.entry(IDS["d"]).link_peers is True and issued.entry(IDS["b"]).link_peers is False
    a.refresh_roster(_inputs())
    assert not a.custody.link_switches_unknown
    t2._settle(pack)

    a.state._commit_many({ROSTER_V2_KEY: None, LINK_SWITCHES_KEY: None})
    a.state.save_takeover_state(None, None)
    handed = a.custody.mint({"master_install_id": IDS["b"]}, strict=True)
    assert a.custody.hand_over_roster(handed)
    t2._settle(pack)
    assert b.custody.settings().master_install_id == IDS["b"] and b.state.alpha_since() == handed.rev[0]
    assert b.custody.roster_v2().generation < b.custody.roster().generation
    before = b.custody.roster_v2().generation
    assert b.refresh_roster(_inputs()) == "" and b.custody.roster_v2().generation == before and b.custody.link_switches_unknown

    d.state._commit_many({ROSTER_V2_KEY: None})
    assert d.custody.merge_roster_v2(first, IDS["a"]) is False and d.state.stored_roster_v2() is None

    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    (tmp_path / "off.json").write_text("{}")
    plain = ConfigState(lambda: tmp_path / "off.json")
    plain.save_roster_v2(first)
    assert plain.stored_roster_v2() is not None and not {LINK_SWITCHES_KEY, "alpha_since"} & set(plain._block())


def test_a_v1_only_issue_or_a_key_lost_between_the_issues_never_leaves_the_switches_unknown(monkeypatch, tmp_path):
    pack, _ = t2._four(monkeypatch, tmp_path, caps_extra=(capabilities.CAP_MESH,))
    a = pack["a"]
    t2._settle(pack, 2)
    assert a.refresh_roster(_inputs()) == "bump:first"
    assert a.refresh_roster(_inputs(), link_peers={IDS["b"]: False}) == "bump:authority"
    real_plan = roster_v2.plan_v2

    def full(*args, **kwargs):
        raise roster_v2.roster_doc.RosterFull(65, 64, [])
    monkeypatch.setattr(roster_v2, "plan_v2", full)
    assert a.refresh_roster(t2._computers(5)) == "bump:membership"
    v1_generation = a.custody.roster().generation
    assert a.state.link_switches()[1] == v1_generation and a.state.link_switches()[2][IDS["b"]] is False
    monkeypatch.setattr(roster_v2, "plan_v2", real_plan)
    a.refresh_roster(_inputs())
    assert not a.custody.link_switches_unknown and a.custody.roster_v2().entry(IDS["b"]).link_peers is False

    def no_key(_roster):
        raise settings_custody.DeviceKeyUnavailable()
    with monkeypatch.context() as lost:
        lost.setattr(a.custody, "_issue_roster_v2", no_key)
        assert a.refresh_roster(t2._computers(6)) == ""
    assert a.custody.roster().generation > v1_generation
    a.refresh_roster(_inputs())
    assert not a.custody.link_switches_unknown and a.custody.roster_v2().entry(IDS["b"]).link_peers is False


def test_the_switch_memory_replay_check_fires_on_its_own(monkeypatch, tmp_path):
    pack, _ = t2._four(monkeypatch, tmp_path, caps_extra=(capabilities.CAP_MESH,))
    a, d = pack["a"], pack["d"]
    t2._settle(pack, 2)
    assert a.refresh_roster(_inputs()) == "bump:first"
    t2._settle(pack)
    current = d.custody.roster_v2_wire()
    d.state._commit_many({ROSTER_V2_KEY: None})
    d.state.advance_link_switches(d.custody.roster().generation + 5, {IDS["b"]: False})
    verdicts = []
    real_judge = roster_v2.judge_v2
    monkeypatch.setattr(roster_v2, "judge_v2", lambda **kw: verdicts.append(real_judge(**kw)) or verdicts[-1])
    assert d.custody.merge_roster_v2(current, IDS["a"]) is False and verdicts == []
    monkeypatch.setattr(roster_v2, "judge_v2", real_judge)

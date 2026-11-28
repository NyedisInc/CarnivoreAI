
from __future__ import annotations

import asyncio
import dataclasses
import random
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401, E402
from src.core.computers import mesh, mesh_choice, view  # noqa: E402
from src.core.computers.mux import frames as mf  # noqa: E402
from src.core.computers.takeover_driver import TakeoverDriver  # noqa: E402
from src.core.pack.machines import capabilities, interim_policy, roster_v2  # noqa: E402
from tests.python.computers.test_mesh_links import A, B, C, _pair, _wait, root  # noqa: E402,F401
from tests.python.pack.test_takeover_v2 import _computers  # noqa: E402


def _list(monkeypatch, inputs=None, **kwargs):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    return roster_v2.plan_v2(None, inputs or _computers(12), alpha=A, **kwargs)


def _ids(n: int = 12):
    return [c.install_id for c in _computers(n)]


def test_choice_table(monkeypatch):
    ids = _ids()
    others = ids[2:]
    lst = _list(monkeypatch)
    assert sorted(mesh_choice.eligible_ids(lst, B)) == sorted(others)
    got = mesh_choice.choose_links(lst, B)
    assert len(got) == 8 == mesh_choice.STANDING_LINKS and set(got) <= set(others) and B not in got and A not in got
    off, nomesh = ids[4], ids[5]
    inputs = [dataclasses.replace(i, capabilities=()) if i.install_id == nomesh else i for i in _computers(12)]
    lst2 = _list(monkeypatch, inputs, link_peers={off: False})
    assert off not in mesh_choice.eligible_ids(lst2, B) and nomesh not in mesh_choice.eligible_ids(lst2, B)
    assert len(mesh_choice.eligible_ids(lst2, B)) == 8
    mine_off = _list(monkeypatch, link_peers={B: False})
    assert mesh_choice.own_switch(mine_off, B) == "off" and mesh_choice.choose_links(mine_off, B) == []
    assert mesh_choice.own_switch(lst, A) == "alpha" and mesh_choice.choose_links(lst, A) == []
    assert mesh_choice.own_switch(None, B) == "no_list" and mesh_choice.choose_links(None, B) == []
    assert mesh_choice.own_switch(lst, "nobody") == "off"
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert mesh_choice.own_switch(lst, B) == "off" and mesh_choice.choose_links(lst, B) == []
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    worst = max(others, key=lambda p: mesh_choice.pair_key(B, p))
    kept = mesh_choice.choose_links(lst, B, connected={worst}, excluded={worst}, reachable=set(others) - {worst}, cap=3)
    assert kept[0] == worst and len(kept) == 3
    gone = got[0]
    assert mesh_choice.choose_links(lst, B, reachable=set(others) - {gone}, cap=10)[-1] == gone
    assert gone not in mesh_choice.choose_links(lst, B, reachable=set(others) - {gone})
    laptops = set(others[:5])
    lap = _list(monkeypatch, [dataclasses.replace(i, laptop=i.install_id in laptops) for i in _computers(12)])
    assert not set(mesh_choice.choose_links(lap, B, cap=5)) & laptops
    assert set(mesh_choice.choose_links(lap, B, cap=10)) == set(others)
    assert gone not in mesh_choice.choose_links(lst, B, excluded={gone})
    shuffled = _computers(12)
    random.Random(7).shuffle(shuffled)
    again = _list(monkeypatch, shuffled)
    assert sorted(mesh_choice.choose_links(again, B)) == sorted(got)
    assert mesh_choice.choose_links(lst, B, connected=list(reversed(others[:3])), reachable=frozenset(others), excluded=[gone]) \
        == mesh_choice.choose_links(lst, B, connected=set(others[:3]), reachable=list(others), excluded={gone})
    assert lap.entry(others[0]).laptop and not lst.entry(others[0]).laptop
    assert "laptop" not in lap.as_v1().computers[0].model_dump()
    moved = roster_v2.plan_v2(lst, [dataclasses.replace(i, laptop=True) for i in _computers(12)], alpha=A)
    assert moved.entry(others[0]).laptop and roster_v2.bump_reason_v2(lst, moved) is None


def test_exclusions_on_a_fake_clock():
    ex = mesh_choice.Exclusions()
    ex.observe("b", True, 0.0)
    assert ex.excluded(119.0) == frozenset()
    ex.observe("b", True, 119.5)
    assert ex.excluded(120.0) == frozenset({"b"})
    assert ex.excluded(719.0) == frozenset({"b"})
    assert ex.excluded(721.0) == frozenset()
    ex.observe("c", True, 1000.0)
    ex.observe("c", False, 1100.0)
    ex.observe("c", True, 1110.0)
    assert ex.excluded(1200.0) == frozenset()
    assert ex.excluded(1230.0) == frozenset({"c"})
    ex.forget("c")
    assert ex.excluded(1231.0) == frozenset()


def test_on_demand_link_is_dialed_for_one_action_then_released(monkeypatch, tmp_path, root):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(mesh_choice, "STANDING_LINKS", 0)
    monkeypatch.setattr(mesh, "FETCH_DEBOUNCE", 0.0)
    now = [1000.0]

    async def scenario() -> None:
        async with _pair(root, tmp_path, clocks={"b": lambda: now[0]}) as p:
            links = p.links
            await asyncio.sleep(0.3)
            assert links["b"]._sessions == {} and links["c"]._sessions == {}
            assert await links["b"].ensure(A) is False
            assert await links["b"].ensure(C) is True
            sb = links["b"]._sessions[C]
            assert sb.dialed_by_me is True
            entry = next(e for e in links["b"].snapshot()["links"] if e["install_id"] == C)
            assert (entry["state"], entry["dialed_by"], entry["on_demand"], entry["standing"]) == ("linked", "this", True, False)
            await _wait(lambda: B in links["c"]._sessions)
            sc = links["c"]._sessions[B]
            now[0] += mesh.ON_DEMAND_IDLE_SECONDS + 1
            await links["b"]._sweep()
            await asyncio.wait_for(sc.mux.closed.wait(), 5)
            assert sc.mux.goaway_reason == mf.GO_NORMAL
            assert links["b"]._dialer._dials == {}
            await asyncio.sleep(0.5)
            assert links["b"]._sessions == {} and links["c"]._sessions == {}

    asyncio.run(scenario())


def test_the_33rd_inbound_mesh_link_is_closed_before_the_hello(monkeypatch):
    links = mesh.MeshLinks(identity=SimpleNamespace(cert=SimpleNamespace(link_fid="f", cert_sha256="0" * 64)), iid="me", listener=None, custody=lambda: None,
                           after_change=None, star_linked=lambda _i: 0.0)
    links._allowed = {"s": C}
    links._sessions = {f"p{i}": object() for i in range(mesh.MAX_MESH_LINKS)}
    monkeypatch.setattr(mesh.MeshLinks, "_sha_of", staticmethod(lambda _w: "s"))

    async def boom(*_a, **_k):
        raise AssertionError("the HELLO ran")

    monkeypatch.setattr(mesh, "open_session", boom)
    closed = []
    writer = SimpleNamespace(close=lambda: closed.append(True))
    asyncio.run(links.accept(None, writer, C))
    assert closed == [True]
    del links._sessions["p0"]
    with pytest.raises(AssertionError, match="HELLO"):
        asyncio.run(links.accept(None, writer, C))


def test_reachable_is_the_fresh_walk_or_none():
    driver = TakeoverDriver(SimpleNamespace(), clock=lambda: 100.0)
    assert driver.reachable() is None
    peers = {B: interim_policy.Peer(True, False), C: interim_policy.Peer(False, False)}
    driver._walker = SimpleNamespace(walk=interim_policy.Walk(90.0, peers))
    assert driver.reachable() == frozenset({B})
    driver._walker = SimpleNamespace(walk=interim_policy.Walk(100.0 - interim_policy.WALK_FRESH_SECONDS - 1, peers))
    assert driver.reachable() is None


def test_view_has_the_mesh_key_only_while_the_switch_is_on(monkeypatch):
    rt = SimpleNamespace(iid=A, label="a", link_state="stopped", invites=None, fed_key=None, join_server=None, addresses=[], findable=lambda: None,
                         link_port=None)
    monkeypatch.setattr(view, "stored_computers", lambda _rt, _links: [])
    monkeypatch.setattr(mesh, "_ACTIVE", None)
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert "mesh" not in view.build_view(rt, None)
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    out = view.build_view(rt, None)
    assert "mesh" in out and out["mesh"] is None

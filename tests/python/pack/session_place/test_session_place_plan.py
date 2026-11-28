
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.core.pack.jobs import boot, needs_policy, place, policy as policy_mod
from src.core.pack.jobs.install import CAP_INSTALL
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import CAP_JOBS, JobError
from src.core.pack.placement import rule
from src.core.pack.placement.needs import parse_need
from src.core.pack.placement.workload import resolve
from src.core.pack.reserve.holds import HOLDS
from src.core.pack.session_place import decide as decide_mod, plan as plan_mod
from src.core.pack.session_place.types import CAP_SESSION_PLACE, PlaceRequest

UID = "p1x23456"
A, B, C = "iid-a", "iid-b", "iid-c"
REQ = PlaceRequest(project="app")
CAPS = [CAP_JOBS, CAP_SESSION_PLACE]


def snap(load1: float, *, may_host: bool = True, tools: Optional[Dict[str, bool]] = None, xcode: bool = False, brew: bool = False) -> Dict[str, Any]:
    return {"load": {"cores": 10, "load_1": load1, "mem_total_gb": 32.0, "mem_available_gb": 28.0, "disk_free_gb": 200.0},
            "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}, "toolchain": {}, "restrictions": {"may_host_agents": may_host},
            "can": {"tools": {"claude": True, "ffmpeg": False, **(tools or {})}, "xcode": xcode, "brew": brew}}


def peer(iid: str, label: str, load: float = 1.0, **kw: Any) -> rule.MachineInput:
    return rule.MachineInput(iid, label, snap(load, **kw), True, False, False, True, None)


def view(self_load: float, peers: List[rule.MachineInput], *, master: str = A, home: bool = True, caps: Any = None,
         self_snap: Optional[Dict[str, Any]] = None) -> place.PlaceView:
    me = rule.MachineInput(A, "nostromo", self_snap or snap(self_load), True, True, home, True, 0)
    return place.PlaceView(me, peers, caps if caps is not None else {p.install_id: list(CAPS) for p in peers}, master)


@pytest.fixture(autouse=True)
def _empty_holds():
    HOLDS._entries.clear()
    yield
    HOLDS._entries.clear()


@pytest.fixture()
def store(tmp_path) -> JobStore:
    return JobStore(tmp_path / "state")


def pol(store: JobStore, *, on: bool = True, never_use: Optional[List[str]] = None) -> policy_mod.Policy:
    policy_mod.set_auto(store, UID, on)
    if never_use:
        policy_mod.set_lists(store, UID, never_use=never_use)
    return policy_mod.get(store, UID)


COPIES = {B: "/w/app-b", C: "/w/app-c"}


def test_mark_off_is_here(store):
    got = plan_mod.plan(REQ, pol(store, on=False), view(9.8, [peer(B, "tower")]), [], COPIES)
    assert (got.decision, got.reason) == ("here", "project is set to this computer only")


def test_not_the_home_is_here(store):
    got = plan_mod.plan(REQ, pol(store), view(9.8, [peer(B, "tower")], home=False), [], COPIES)
    assert got.decision == "here" and "not the project's home" in got.reason


def test_not_pegged_is_here_with_its_room(store):
    got = plan_mod.plan(REQ, pol(store), view(1.0, [peer(B, "tower", 0.5)]), [], COPIES)
    assert got.decision == "here" and got.reason.startswith("this computer has room")


def test_pegged_with_a_peer_that_has_room_and_a_copy_is_remote(store):
    got = plan_mod.plan(REQ, pol(store), view(9.8, [peer(B, "tower")]), [], COPIES)
    assert (got.decision, got.install_id, got.label, got.copy_root) == ("remote", B, "tower", "/w/app-b")
    assert got.wire()["computer"] == B and not got.code


def test_a_peer_without_a_copy_is_skipped_with_its_reason(store):
    got = plan_mod.plan(REQ, pol(store), view(9.8, [peer(B, "tower")]), [], {})
    assert got.decision == "here" and "tower has no copy of this project" in got.reason


def test_a_peer_without_the_capability_is_skipped_with_its_reason(store):
    got = plan_mod.plan(REQ, pol(store), view(9.8, [peer(B, "tower")], caps={B: [CAP_JOBS]}), [], COPIES)
    assert got.decision == "here" and "tower runs an older carnivore" in got.reason


def test_never_use_and_takes_work_off_skip_their_computers(store):
    v = view(9.8, [peer(B, "tower"), peer(C, "mini", may_host=False)])
    got = plan_mod.plan(REQ, pol(store, never_use=["tower"]), v, [], COPIES)
    assert got.decision == "here"
    assert "tower is on the never use list" in got.reason and "mini" in got.detail and "may_host_agents" in got.reason


def test_a_member_computer_places_only_on_the_main_computer(store):
    both = view(9.8, [peer(B, "tower"), peer(C, "mini")], master=C)
    assert plan_mod.plan(REQ, pol(store), both, [], COPIES).install_id == C
    only_other = plan_mod.plan(REQ, pol(store), view(9.8, [peer(B, "tower")], master=C), [], COPIES)
    assert only_other.decision == "here" and "tower is not the master" in only_other.reason


def test_a_need_only_the_laptop_meets_leaves_even_when_here_has_room(store):
    v = view(1.0, [peer(B, "laptop", 0.5, xcode=True), peer(C, "mini", 0.5)])
    got = plan_mod.plan(REQ, pol(store), v, plan_mod.merge_needs(["xcode"], []), COPIES)
    assert (got.decision, got.install_id) == ("remote", B)
    same = plan_mod.plan(REQ, pol(store), v, [], COPIES)
    assert same.decision == "here"


def test_a_need_nobody_meets_is_refused_and_never_proposes_an_install(store):
    peers = [peer(B, "tower", 0.5, brew=True)]
    v = view(1.0, peers, caps={B: [*CAPS, CAP_INSTALL]})
    need = [parse_need("ffmpeg")]
    job = place.place(resolve({"kind": "suite"}), UID, pol(store), v, needs=need)
    assert job.decision == "remote" and job.install
    got = plan_mod.plan(REQ, pol(store), v, need, COPIES)
    assert got.decision == "refused" and got.code == "requirement_unmet" and not got.install_id
    assert "ffmpeg" in got.reason and "start this session" in got.reason and "tower" in got.detail


def test_a_need_that_is_unmet_here_but_met_by_a_computer_with_no_copy_is_refused(store):
    v = view(1.0, [peer(B, "laptop", 0.5, xcode=True)])
    got = plan_mod.plan(REQ, pol(store), v, [parse_need("xcode")], {})
    assert got.decision == "refused" and "laptop has no copy" in got.detail


def test_the_agent_binary_is_a_target_filter_never_a_refusal_for_this_computer(store):
    no_claude = peer(B, "tower", 0.5, tools={"claude": False})
    pegged = plan_mod.plan(REQ, pol(store), view(9.8, [no_claude]), [], COPIES)
    assert pegged.decision == "here"
    shell = plan_mod.plan(PlaceRequest(project="app", family="shell"), pol(store), view(9.8, [no_claude]), [], COPIES)
    assert shell.decision == "remote"
    bare = {**snap(1.0), "can": {}}
    assert plan_mod.plan(REQ, pol(store), view(1.0, [], self_snap=bare), [], COPIES).decision == "here"


def test_the_reason_stays_under_160_characters(store):
    names = [peer(f"iid-{i}", "a-very-long-computer-name-" + str(i), 1.0, may_host=False) for i in range(6)]
    for needs in ([], [parse_need("xcode")]):
        got = plan_mod.plan(REQ, pol(store), view(9.8, names, self_snap=snap(9.8)), needs, {p.install_id: "/w" for p in names})
        assert len(got.reason) <= 160
        assert len(got.detail) > 160 or got.decision == "here"
    assert len(plan_mod.clip("x" * 400)) == 160 and plan_mod.clip("short") == "short"


def test_plan_takes_no_hold_and_reads_the_session_kind_as_light(store):
    plan_mod.plan(REQ, pol(store), view(1.0, [peer(B, "tower")]), [], COPIES)
    assert HOLDS.total()[2] == 0
    work = resolve({"kind": "session"})
    assert (work.est_cpu_cores, work.est_ram_gb, work.heavy) == (0.5, 0.8, False)


def test_needs_policy_accepts_the_session_key(store):
    assert "session" in needs_policy.KINDS
    needs_policy.put(store, UID, {"session": {"needs": ["xcode"], "prefer": ["gpu"]}})
    assert needs_policy.get(store, UID, "session") == (["xcode"], ["gpu"])
    with pytest.raises(ValueError):
        needs_policy.put(store, UID, {"nonsense": {"needs": []}})
    assert [n.text for n in plan_mod.merge_needs(["mem_gb>=16"], ["xcode", "mem_gb>=16"])] == ["mem_gb>=16", "xcode"]
    with pytest.raises(ValueError):
        plan_mod.merge_needs(["warp drive"], [])


def test_store_tables_for_placements_and_automations(store):
    assert store.placement_get("r" * 32) is None
    store.placement_put("r" * 32, project_uid=UID, install_id=B, label="tower", decision="remote", reason="why", starter_kind="agent")
    store.placement_put("r" * 32, session_id="remote:peer-b:cc_1", session_uuid="u1")
    row = store.placement_get("r" * 32)
    assert row["label"] == "tower" and row["session_id"] == "remote:peer-b:cc_1" and row["starter_kind"] == "agent"
    assert [r["request_id"] for r in store.placement_list(UID)] == ["r" * 32] and store.placement_list("other") == []
    with pytest.raises(JobError):
        store.placement_put("x", nope=1)
    assert store.automation_placement_get("auto_1") is None
    store.automation_placement_set("auto_1", "auto")
    assert store.automation_placement_get("auto_1") == "auto"
    with pytest.raises(JobError):
        store.automation_placement_set("auto_1", "elsewhere")
    store.automation_placement_delete("auto_1")
    assert store.automation_placement_get("auto_1") is None


def test_decide_reads_policy_needs_copies_and_view_and_writes_nothing(store, monkeypatch):
    pol(store)
    needs_policy.put(store, UID, {"session": {"needs": ["xcode"], "prefer": []}})
    seen: List[str] = []

    def view_for(root: str, uid: str) -> place.PlaceView:
        seen.append(root)
        return view(1.0, [peer(B, "laptop", 0.5, xcode=True)])

    engine = SimpleNamespace(store=store, _view_for=view_for)
    monkeypatch.setitem(boot._built, "engine", engine)
    monkeypatch.setattr(decide_mod, "_project_of", lambda req, eng: (UID, "app", "/w/app"))
    monkeypatch.setattr(decide_mod, "_copies", lambda eng, uid: {B: "/w/app-b"})
    got = asyncio.run(decide_mod.decide(None, PlaceRequest(project="app")))
    assert (got.decision, got.install_id, got.copy_root, got.project_uid, got.project_name) == ("remote", B, "/w/app-b", UID, "app")
    assert seen == ["/w/app"] and store.placement_list(UID) == []
    monkeypatch.setattr(decide_mod, "_copies", lambda eng, uid: {})
    assert asyncio.run(decide_mod.decide(None, PlaceRequest(project="app"))).decision == "refused"
    with pytest.raises(JobError) as bad:
        asyncio.run(decide_mod.decide(None, PlaceRequest(project="app", needs=["warp drive"])))
    assert bad.value.code == "bad_needs"
    monkeypatch.setitem(boot._built, "engine", SimpleNamespace(store=store, _view_for=lambda r, u: (_ for _ in ()).throw(
        JobError("pack_not_running", "the Pack is not running on this computer", 503))))
    assert asyncio.run(decide_mod.decide(None, PlaceRequest(project="app"))).decision == "here"
    monkeypatch.undo()
    with pytest.raises(JobError) as off:
        asyncio.run(decide_mod.decide(None, PlaceRequest(project="app")))
    assert off.value.code in ("jobs_not_ready",)

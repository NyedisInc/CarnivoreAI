
from __future__ import annotations

import asyncio
import dataclasses
import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.core.federation import mesh_peers, peer_links
from src.core.pack.jobs import engine as engine_mod, land, member_link, member_view, needs_model, paths, policy as policy_mod, snapshot
from src.core.pack.jobs.engine import Engine
from src.core.pack.jobs.member_view import Deps, Facts, MemberView
from src.core.pack.jobs.place import PlaceView, place, unfit_reason
from src.core.pack.jobs import engine_run, host as host_mod, host_admit
from src.core.pack.jobs.types import CAP_JOBS, CollectAnswer, HostState, JobError, JobRecord, JobRequest, JobState
from src.core.pack.machines import restrictions as restrictions_mod
from src.core.pack.machines import capabilities
from src.core.pack.placement import rule
from src.core.pack.placement.workload import Workload
from src.core.pack.relay import member_reach

UID = "uid-test-0001"
C, D, E = "iid-c", "iid-d", "iid-e"
CAPS = [CAP_JOBS, capabilities.CAP_JOBS_MESH]


def rich(load1: float, iid: str = "", *, pegged: bool = False) -> Dict[str, Any]:
    doc = {"load": {"cores": 10, "load_1": load1, "mem_total_gb": 32.0, "mem_available_gb": 28.0, "disk_free_gb": 200.0},
           "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}, "toolchain": {}, "restrictions": {"may_host_agents": True},
           "can": {"v": 1, "brew": False, "tools": {}, "labels": []}, "pressure": {"v": 1, "pegged": pegged}}
    return {**doc, "install_id": iid} if iid else doc


class Fakes:

    def __init__(self) -> None:
        self.facts = Facts(members=[C, D], labels={C: "c-label", D: "d-label"}, home="iid-b", counterparts={C, D}, cards={C: 10, D: 10},
                           linked={C, D}, free_on_demand=8)
        self.answers: Dict[str, Any] = {C: (200, {"snapshot": rich(1.0, C), "project": "ok"}), D: (200, {"snapshot": rich(1.0, D), "project": "ok"})}
        self.caps_map: Dict[str, Optional[List[str]]] = {C: CAPS, D: CAPS, E: CAPS}
        self.looks: List[Any] = []
        self.reads = 0
        self.now = 1000.0

    def read(self, root: str, uid: str, self_iid: str, store: Any) -> Facts:
        self.reads += 1
        return self.facts

    async def look(self, iid: str, uid: str, dial: bool) -> Any:
        self.looks.append((iid, dial))
        return self.answers[iid]

    def deps(self) -> Deps:
        return Deps(read=self.read, look=self.look, caps=lambda iid: self.caps_map.get(iid), clock=lambda: self.now)


class FakeTarget:

    def __init__(self, iid: str, calls: List[Any], plan: Dict[str, Any]) -> None:
        self.install_id, self.label, self._calls, self._plan = iid, iid + "-label", calls, plan

    def _go(self, verb: str) -> None:
        self._calls.append((self.install_id, verb))
        todo = self._plan.get((self.install_id, verb), self._plan.get(verb))
        if callable(todo):
            todo()
        elif todo is not None:
            raise todo

    async def admit(self, body: Any) -> None:
        self._go("admit")

    async def start(self, body: Any) -> str:
        self._go("start")
        return "preparing"

    async def collect(self, job_id: str) -> CollectAnswer:
        self._go("collect")
        return CollectAnswer()

    async def status(self, job_id: str) -> Any:
        self._go("status")
        return SimpleNamespace(state=HostState.EXITED, exit_code=0, output_tail="", detail="")

    async def release(self, job_id: str) -> None:
        self._go("release")

    async def stop(self, job_id: str, keep_files: bool) -> None:
        self._go("stop")


class Clock:

    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Reg:

    def capabilities(self, iid: str) -> Any:
        return None

    def client(self, iid: str) -> Any:
        return None


class Links:

    def client(self, iid: str) -> Any:
        return None

    def capabilities(self, iid: str) -> List[str]:
        return []


@pytest.fixture()
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(mesh_peers, "REGISTRY", Reg())
    monkeypatch.setattr(peer_links, "LINKS", Links())
    monkeypatch.setattr(member_reach, "member_ids", lambda: [C, D])
    monkeypatch.setattr(member_reach, "member_ids_held", lambda: [C, D])
    monkeypatch.setattr(member_reach, "listed_ids_held", lambda: [C, D])
    root, state, jobs = tmp_path / "proj", tmp_path / "state", tmp_path / "jobs"
    for folder in (root, state, jobs):
        folder.mkdir()
    db_file = tmp_path / "projects.db"
    with closing(sqlite3.connect(db_file)) as conn:
        conn.execute("CREATE TABLE projects (uid TEXT PRIMARY KEY, air_gap INTEGER)")
        conn.execute("INSERT INTO projects VALUES (?, 0)", (UID,))
        conn.commit()
    fakes, calls, plan, wall, mono = Fakes(), [], {}, Clock(), Clock(50.0)

    async def passthrough(answer: Any, *_a: Any, **_k: Any) -> Any:
        return answer

    async def sleep(seconds: float) -> None:
        mono.now += seconds
        wall.now += seconds
        await asyncio.sleep(0)

    async def carry(*_a: Any) -> None:
        calls.append(("carry",))

    fake_snap = SimpleNamespace(toplevel=str(root), head=None, scope="", notes=[], dep_dirs=[], commit="a" * 40, tree="b" * 40, taken_at=1.0)
    monkeypatch.setattr(needs_model, "refine", passthrough)
    monkeypatch.setattr(snapshot, "take", lambda *_a, **_k: fake_snap)
    me = rule.MachineInput("iid-b", "b", rich(0.5, pegged=True), True, True, True, True, 0)
    eng = Engine(state_dir=state, jobs_root=jobs, install_id="iid-b", open_db=lambda: sqlite3.connect(db_file), clock=wall, sleep=sleep, mono=mono,
                 view_for=lambda _r, _u: PlaceView(me, [], {}, "iid-alpha", None), target_for=lambda iid: FakeTarget(iid, calls, plan),
                 carry_commits=carry, members=MemberView(fakes.deps()), lost_after_s=90.0)
    eng._resolve_project = lambda folder: ({"uid": UID, "name": "app", "root": str(root)}, "")  # type: ignore[method-assign]
    policy_mod.set_auto(eng.store, UID, True)
    return SimpleNamespace(eng=eng, fakes=fakes, calls=calls, plan=plan, root=root, jobs=jobs, wall=wall, mono=mono, me=me)


def job(r: SimpleNamespace, folder: Optional[Path] = None) -> JobRequest:
    return JobRequest(command="echo hi", folder=str(folder or r.root), kind="suite", caller_session="ses_test", time_cap_s=60)


def propose(r: SimpleNamespace, folder: Optional[Path] = None) -> JobRecord:
    return asyncio.run(r.eng.propose(job(r, folder)))


def seed(r: SimpleNamespace, state: JobState, *, member: bool, peer: str = C) -> JobRecord:
    ctx = {"request": dataclasses.asdict(job(r)), **({"member": True} if member else {}),
           "snap": {"toplevel": str(r.root), "head": None, "scope": "", "project_root": str(r.root), "notes": [], "roots": [str(r.root)], "dep_dirs": []}}
    job_id = paths.new_job_id()
    return r.eng.store.create_job(JobRecord(id=job_id, idem_key=job_id, project_uid=UID, project_name="app", request_json=json.dumps(ctx), state=state,
                                            peer_install_id=peer, peer_label=peer + "-label", snapshot_commit="a" * 40, created_at=r.wall(), updated_at=r.wall()))


def test_switch_off_is_master(rig, monkeypatch) -> None:
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    me = rule.MachineInput("iid-b", "b", rich(0.5, pegged=True), True, True, True, True, 0)
    star = rule.MachineInput("iid-s", "s", rich(1.0), True, False, False, True, None)
    view = PlaceView(me, [star], {"iid-s": [CAP_JOBS]}, "iid-s")
    assert unfit_reason(rule.MachineInput(C, "c", None), dataclasses.replace(view, master_id="iid-a"), UID) == "is not the master and this computer is not either"
    assert view.mesh_members == frozenset() and view.member_notes == {}
    assert place(Workload(), UID, policy_mod.Policy(UID, auto_delegate=True), view).peer_install_id == "iid-s"
    rig.eng._view_for = lambda _r, _u: view
    rec = propose(rig)
    assert rec.state == JobState.WAITING_APPROVAL and rec.peer_install_id == "iid-s" and "member" not in json.loads(rec.request_json)
    assert rig.fakes.reads == 0 and rig.fakes.looks == [] and rig.calls == [("iid-s", "admit")]
    mv = asyncio.run(MemberView(rig.fakes.deps()).extend(view, "root", UID, store=None, self_iid="iid-b"))
    assert mv is view and rig.fakes.reads == 0


def test_a_fresh_ok_look_sends_the_job_to_c_with_the_member_mark(rig) -> None:
    rig.fakes.facts.counterparts = {C}
    rec = propose(rig)
    assert rec.state == JobState.WAITING_APPROVAL and rec.peer_install_id == C and json.loads(rec.request_json)["member"] is True
    assert rig.fakes.looks == [(C, False)] and rig.calls == [(C, "admit")]


def test_a_stale_card_is_never_a_candidate(rig) -> None:
    rig.fakes.facts.cards[D] = member_view.CARD_MAX_AGE_S + 1
    rec = propose(rig)
    assert rec.peer_install_id == C and (D, False) not in rig.fakes.looks and all(c[0] != D for c in rig.calls)
    rig.fakes.facts.cards.pop(C)
    rig.fakes.looks.clear()
    assert asyncio.run(rig.eng._members.extend(rig.eng._view_for("", ""), "r", UID, store=rig.eng.store, self_iid="iid-b")).peers == []
    assert rig.fakes.looks == []


def test_an_old_look_whose_relook_fails_means_not_connected(rig) -> None:
    rig.fakes.facts.members, rig.fakes.facts.counterparts = [C], {C}
    mv = rig.eng._members
    base = PlaceView(rig.me, [], {}, "iid-alpha")
    first = asyncio.run(mv.extend(base, "r", UID, store=None, self_iid="iid-b"))
    assert first.peers[0].usable and len(rig.fakes.looks) == 1
    asyncio.run(mv.extend(base, "r", UID, store=None, self_iid="iid-b"))
    assert len(rig.fakes.looks) == 1, "inside 30 s the look is cached"
    rig.fakes.now += member_view.LOOK_FRESH_S + 1
    rig.fakes.answers[C] = (0, None)
    second = asyncio.run(mv.extend(base, "r", UID, store=None, self_iid="iid-b"))
    assert len(rig.fakes.looks) == 2 and second.peers[0].snapshot is None and not second.peers[0].usable
    answer = place(Workload(), UID, policy_mod.Policy(UID, auto_delegate=True), second)
    assert answer.decision == "here" and "its link is down" in json.dumps(answer.why) + answer.reason, answer


def test_a_verdict_other_than_ok_or_records_that_lack_c_mean_not_chosen(rig) -> None:
    rig.fakes.facts.members, rig.fakes.facts.counterparts = [C], {C}
    rig.fakes.answers[C] = (200, {"snapshot": rich(1.0, C), "project": "project_not_here"})
    view = asyncio.run(rig.eng._members.extend(PlaceView(rig.me, [], {}, "iid-alpha"), "r", UID, store=None, self_iid="iid-b"))
    assert view.peers[0].has_project is False and C not in view.member_notes
    answer = place(Workload(), UID, policy_mod.Policy(UID, auto_delegate=True), view)
    assert answer.decision == "here" and "the project is not on this machine" in json.dumps(answer.why) + answer.reason, answer
    rig.fakes.answers[C] = (200, {"snapshot": rich(1.0, C), "project": "no_harness"})
    rig.eng._members._cache.clear()
    assert asyncio.run(rig.eng._members.extend(PlaceView(rig.me, [], {}, "iid-alpha"), "r", UID, store=None, self_iid="iid-b")).member_notes[C] \
        == "would not take this project's work (no_harness)"
    rig.fakes.facts.counterparts = set()
    rig.fakes.looks.clear()
    assert asyncio.run(rig.eng._members.extend(PlaceView(rig.me, [], {}, "iid-alpha"), "r", UID, store=None, self_iid="iid-b")).peers == []
    assert rig.fakes.looks == []


def test_a_one_way_computer_and_a_one_way_self_are_never_looked_at(rig) -> None:
    rig.fakes.facts.members = [D]
    rec = propose(rig)
    assert rec.peer_install_id == D and all(look[0] != C for look in rig.fakes.looks)
    rig.fakes.facts.self_one_way = True
    rig.fakes.looks.clear()
    base = PlaceView(rig.me, [], {}, "iid-alpha")
    assert asyncio.run(rig.eng._members.extend(base, "r", UID, store=None, self_iid="iid-b")) is base and rig.fakes.looks == []


def test_a_received_job_is_never_placed_again(rig, tmp_path) -> None:
    slot = rig.jobs / "slots" / "job-x" / "work"
    slot.mkdir(parents=True)
    rec = propose(rig, slot)
    assert rec.state == JobState.HERE and rec.reason == member_view.NO_CHAIN and rig.fakes.looks == [] and rig.fakes.reads == 0 and rig.calls == []
    capabilities.MESH_BUILD_ON = False
    try:
        rec = propose(rig, slot)
    finally:
        capabilities.MESH_BUILD_ON = True
    assert rec.reason != member_view.NO_CHAIN


def test_a_closed_member_power_moves_the_job_on_and_never_fails_it(rig) -> None:
    rig.plan["admit"] = JobError("mesh_power_refused", "closed", 403)
    rec = propose(rig)
    assert rec.state == JobState.HERE and [c for c in rig.calls if c[1] == "admit"] == [(C, "admit"), (D, "admit")]
    rig.plan.clear()
    rig.calls.clear()
    waiting = propose(rig)
    assert waiting.state == JobState.WAITING_APPROVAL

    async def refuse(_rec: Any) -> None:
        raise JobError("mesh_power_refused", "closed", 403)

    rig.eng._mirror_start = refuse  # type: ignore[method-assign]

    async def flow() -> JobRecord:
        await rig.eng.proceed(waiting.id)
        return await rig.eng.wait(waiting.id, 5)

    done = asyncio.run(flow())
    assert done.state == JobState.HERE and done.error_code == "mesh_power_refused", done


def test_dials_are_bounded_and_standing_links_come_first(rig) -> None:
    facts = rig.fakes.facts
    facts.members, facts.counterparts, facts.cards = [C, D, E], {C, D, E}, {C: 1, D: 1, E: 1}
    facts.linked = {C}
    propose(rig)
    assert rig.fakes.looks == [(C, False)]
    facts.linked = set()
    rig.fakes.looks.clear()
    rig.eng._members._cache.clear()
    base = PlaceView(rig.me, [], {}, "iid-alpha")
    asyncio.run(rig.eng._members.extend(base, "r", UID, store=None, self_iid="iid-b"))
    assert rig.fakes.looks == [(C, True), (D, True)]
    facts.free_on_demand = 2
    rig.fakes.looks.clear()
    rig.eng._members._cache.clear()
    view = asyncio.run(rig.eng._members.extend(base, "r", UID, store=None, self_iid="iid-b"))
    assert rig.fakes.looks == [] and all(not p.usable for p in view.peers)
    facts.free_on_demand = 8
    rig.fakes.answers[C] = (0, None)
    rig.fakes.answers[D] = (200, {"snapshot": rich(1.0, D), "project": "ok"})
    rig.eng._members._cache.clear()
    view = asyncio.run(rig.eng._members.extend(base, "r", UID, store=None, self_iid="iid-b"))
    assert {p.install_id: p.usable for p in view.peers} == {C: False, D: True, E: False}


def test_a_member_holding_four_jobs_is_not_chosen(rig) -> None:
    rig.fakes.facts.members, rig.fakes.facts.counterparts, rig.fakes.facts.held = [C], {C}, {C: member_view.MAX_JOBS_PER_MEMBER}
    rec = propose(rig)
    assert rec.state == JobState.HERE and "c-label already holds 4 jobs from this computer" in (rec.reason or "") and rig.fakes.looks == []


def test_a_result_from_a_computer_that_left_the_pack_is_refused(rig, monkeypatch) -> None:
    monkeypatch.setattr(member_reach, "member_ids_held", lambda: [D])
    monkeypatch.setattr(member_reach, "listed_ids_held", lambda: [D])
    monkeypatch.setattr(land, "land", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("landed")))
    rec = seed(rig, JobState.COLLECTING, member=True)
    asyncio.run(rig.eng._run(rec.id))
    row = rig.eng.get(rec.id)
    assert row.state == JobState.FAILED and row.error_code == "peer_left", row
    assert not any(c[1] in ("collect", "release") for c in rig.calls)
    assert JobState.LANDING.value not in [e["state"] for e in rig.eng.store.events(rec.id)]


def test_a_finished_member_result_survives_a_link_flap_and_a_star_job_is_lost(rig) -> None:
    back_at = rig.mono.now + 400.0

    def flap() -> None:
        if rig.mono.now < back_at:
            raise JobError("unreachable", "down", 502)

    rig.plan["collect"] = flap
    rec = seed(rig, JobState.COLLECTING, member=True)
    asyncio.run(rig.eng._run(rec.id))
    row = rig.eng.get(rec.id)
    assert row.state == JobState.DONE, row
    verbs = [c[1] for c in rig.calls]
    assert verbs.count("release") == 1 and verbs.index("release") > max(i for i, v in enumerate(verbs) if v == "collect")
    notes = [e["note"] for e in rig.eng.store.events(rec.id)]
    assert notes.count("waiting for iid-c-label to come back; its result is kept there") == 1
    rig.calls.clear()
    rig.plan["collect"] = JobError("unreachable", "down", 502)
    star = seed(rig, JobState.COLLECTING, member=False)
    asyncio.run(rig.eng._run(star.id))
    assert rig.eng.get(star.id).state == JobState.LOST


def test_a_jobs_own_carry_dials_once_for_a_member_and_never_with_the_switch_off(rig, monkeypatch) -> None:
    dialed: List[str] = []

    async def connect(iid: str) -> Any:
        dialed.append(iid)
        return None, "x"

    monkeypatch.setattr(member_link, "connect_for", connect)
    asyncio.run(rig.eng._carry_commits(str(rig.root), UID, C))
    assert dialed == [C] and ("carry",) in rig.calls
    asyncio.run(rig.eng._carry_commits(str(rig.root), UID, "ssh:abc"))
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    asyncio.run(rig.eng._carry_commits(str(rig.root), UID, C))
    assert dialed == [C]


def test_the_real_registry_never_marks_a_pair_for_a_capabilities_read(tmp_path) -> None:
    touched: List[str] = []
    live = SimpleNamespace(capabilities=list(CAPS), live_client=lambda: object())
    reg = mesh_peers.MeshPeers(open_db=lambda: None, self_iid="iid-b", fed_dir=tmp_path, sign=lambda _m: "", touch=touched.append,  # type: ignore[arg-type]
                               trusted=lambda _i: None, ensure=lambda *_a, **_k: None)
    reg._entries[C] = mesh_peers._Entry(session=None, transport=None, link=live)  # type: ignore[arg-type]
    assert reg.capabilities(C) == CAPS and touched == []
    assert reg.client(C) is not None and touched == [C]


def test_caps_and_hold_follow_the_link_client_for_would_pick(rig, monkeypatch) -> None:
    class StarLinks(Links):
        live = True

        def client(self, iid: str) -> Any:
            return object() if self.live else None

        def capabilities(self, iid: str) -> List[str]:
            return ["star-cap"]

    links = StarLinks()
    monkeypatch.setattr(peer_links, "LINKS", links)
    monkeypatch.setattr(mesh_peers, "REGISTRY", SimpleNamespace(capabilities=lambda _i: list(CAPS), client=lambda _i: None))

    async def go() -> Any:
        return member_link.hold(C)

    assert member_link.caps_for(C) == ["star-cap"] and asyncio.run(go()) is None
    links.live = False
    assert member_link.caps_for(C) == CAPS

    async def held() -> bool:
        task = member_link.hold(C)
        assert task is not None
        task.cancel()
        return True

    assert asyncio.run(held())



WAIT = "waiting for iid-c-label to come back; the job goes on there"


def test_l1_a_running_member_job_waits_for_its_computer_and_is_never_stopped_for_a_down_link(rig, monkeypatch) -> None:
    back_at = rig.mono.now + 400.0

    def flap() -> None:
        if rig.mono.now < back_at:
            raise JobError("unreachable", "down", 502)

    rig.plan["status"] = flap
    rec = seed(rig, JobState.RUNNING, member=True)
    asyncio.run(rig.eng._run(rec.id))
    assert rig.eng.get(rec.id).state == JobState.DONE
    assert [e["note"] for e in rig.eng.store.events(rec.id)].count(WAIT) == 1 and not any(c[1] == "stop" for c in rig.calls)
    rig.calls.clear()
    rig.plan["status"] = JobError("unreachable", "down", 502)
    star = seed(rig, JobState.RUNNING, member=False)
    asyncio.run(rig.eng._run(star.id))
    assert rig.eng.get(star.id).state == JobState.LOST
    late = seed(rig, JobState.RUNNING, member=True)
    rig.eng.store.set_state(late.id, JobState.RUNNING, note=WAIT)
    with rig.eng.store._borrow() as conn:
        conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?", (rig.wall() - engine_run.COLLECT_WAIT_S - 10, late.id))
    asyncio.run(rig.eng._run(late.id))
    assert rig.eng.get(late.id).state == JobState.LOST
    assert [e["note"] for e in rig.eng.store.events(late.id)].count(WAIT) == 1
    holder = {"ids": [C, D]}
    monkeypatch.setattr(member_reach, "member_ids_held", lambda: holder["ids"])
    monkeypatch.setattr(member_reach, "listed_ids_held", lambda: holder["ids"])

    def left() -> None:
        holder["ids"] = [D]
        raise JobError("unreachable", "down", 502)

    rig.plan["status"] = left
    rig.calls.clear()
    gone = seed(rig, JobState.RUNNING, member=True)
    asyncio.run(rig.eng._run(gone.id))
    row = rig.eng.get(gone.id)
    assert row.state == JobState.FAILED and row.error_code == "peer_left"
    assert not any(c[1] in ("stop", "release", "collect") for c in rig.calls)
    asyncio.run(rig.eng.sweep())
    assert sum(1 for c in rig.calls if c[1] == "stop") == 2, "the sweep stops only the two LOST rows (star and window-expired), never the removed computer's FAILED one"


def test_l1_the_wait_note_is_written_once_and_the_window_counts_from_it(rig) -> None:
    rec = seed(rig, JobState.RUNNING, member=True)
    row = rig.eng.get(rec.id)
    assert rig.eng._member_wait(row, WAIT) is False and rig.eng._member_wait(rig.eng.get(rec.id), WAIT) is False
    assert [e["note"] for e in rig.eng.store.events(rec.id)].count(WAIT) == 1
    rig.wall.now = rig.eng.get(rec.id).updated_at + engine_run.COLLECT_WAIT_S + 1
    assert rig.eng._member_wait(rig.eng.get(rec.id), WAIT) is True


def test_l2_an_unreadable_list_waits_and_a_readable_list_without_c_refuses(rig, monkeypatch) -> None:
    answers: List[Any] = [None, None, [C, D]]
    monkeypatch.setattr(member_reach, "member_ids_held", lambda: answers.pop(0) if len(answers) > 1 else answers[0])
    monkeypatch.setattr(member_reach, "listed_ids_held", lambda: answers.pop(0) if len(answers) > 1 else answers[0])
    rec = seed(rig, JobState.COLLECTING, member=True)
    asyncio.run(rig.eng._run(rec.id))
    assert rig.eng.get(rec.id).state == JobState.DONE
    verbs = [c[1] for c in rig.calls]
    assert verbs.count("collect") == 1 and verbs.count("release") == 1
    assert any("waiting for iid-c-label" in e["note"] for e in rig.eng.store.events(rec.id))
    monkeypatch.setattr(member_reach, "member_ids_held", lambda: [D])
    monkeypatch.setattr(member_reach, "listed_ids_held", lambda: [D])
    rig.calls.clear()
    gone = seed(rig, JobState.COLLECTING, member=True)
    asyncio.run(rig.eng._run(gone.id))
    assert rig.eng.get(gone.id).error_code == "peer_left" and rig.calls == []


def test_l3_two_concurrent_placements_cannot_put_a_fifth_job_on_one_member(rig) -> None:
    for _ in range(3):
        seed(rig, JobState.WAITING_APPROVAL, member=True)
    facts = rig.fakes.facts
    facts.members, facts.counterparts, facts.held = [C], {C}, {C: 3}
    barrier = threading.Barrier(2, timeout=5)

    def read(root: str, uid: str, self_iid: str, store: Any) -> Facts:
        barrier.wait()
        return facts

    rig.eng._members = MemberView(Deps(read=read, look=rig.fakes.look, caps=lambda iid: CAPS, clock=lambda: rig.fakes.now))

    async def both() -> List[JobRecord]:
        return list(await asyncio.gather(rig.eng.propose(dataclasses.replace(job(rig), command="echo one")),
                                         rig.eng.propose(dataclasses.replace(job(rig), command="echo two"))))

    out = asyncio.run(both())
    waiting = [r for r in out if r.state == JobState.WAITING_APPROVAL and r.peer_install_id == C]
    here = [r for r in out if r.state == JobState.HERE]
    assert len(waiting) == 1 and len(here) == 1 and "already holds 4 jobs from this computer" in here[0].reason
    assert sum(1 for r in rig.eng.store.list_jobs(limit=500, live_only=True) if r.peer_install_id == C) == 4


def test_l6_look_shares_a_snapshot_only_for_ok_and_project_not_here_and_a_coded_refusal_keeps_its_note(rig, monkeypatch) -> None:
    monkeypatch.setattr(host_admit, "own_snapshot", lambda: {"can": {"mine": 1}, "restrictions": {"allowed_projects": ["SENTINEL"]}})
    verdicts = {"ok": None, "project_not_here": JobError("project_not_here", "x", 409), "not_a_counterpart": JobError("not_a_counterpart", "x", 403),
                "pack_restricted": JobError("pack_restricted", "x", 403)}
    for code, err in verdicts.items():
        def gate(*_a: Any, _e: Any = err, **_k: Any) -> None:
            if _e is not None:
                raise _e

        out = asyncio.run(host_mod.Host.look(SimpleNamespace(_gate_sync=gate, _restrictions=restrictions_mod.Restrictions, _live_agents=lambda: 0), "iid-b", UID))
        assert out["project"] == code and out["snapshot"] == ({"can": {"mine": 1}} if code in ("ok", "project_not_here") else None), (code, out)
    rig.fakes.facts.members, rig.fakes.facts.counterparts = [C], {C}
    rig.fakes.answers[C] = (200, {"snapshot": None, "project": "pack_restricted"})
    view = asyncio.run(rig.eng._members.extend(PlaceView(rig.me, [], {}, "iid-alpha"), "r", UID, store=None, self_iid="iid-b"))
    assert view.member_notes[C] == "would not take this project's work (pack_restricted)"


def test_m3_a_member_result_lands_as_hostile_input_and_a_star_result_is_unchanged(rig, monkeypatch) -> None:
    from src.core.pack.jobs import engine_run

    seen: Dict[str, Any] = {}

    async def collect(_self: Any, _job: str) -> CollectAnswer:
        return CollectAnswer(blob_id="blob", result_commit="c" * 40, changed=1)

    async def fetch_result(_self: Any, _job: str, _answer: Any, _state: Any) -> str:
        return "p"

    def fetch_bundle(*_a: Any, **kw: Any) -> str:
        seen["fsck"] = kw.get("fsck")
        return "c" * 40

    monkeypatch.setattr(FakeTarget, "collect", collect)
    monkeypatch.setattr(FakeTarget, "fetch_result", fetch_result, raising=False)
    monkeypatch.setattr(engine_run.bundle_io, "fetch_bundle", fetch_bundle)
    monkeypatch.setattr(engine_run.bundle_io, "consumed", lambda *_a, **_k: None)
    monkeypatch.setattr(rig.eng, "_is_child_of", lambda *_a: True)
    monkeypatch.setattr(land, "land", lambda *_a, **kw: seen.update(skip=tuple(kw["skip"])) or land.LandResult())
    for member in (True, False):
        seen.clear()
        rec = seed(rig, JobState.COLLECTING, member=member)
        asyncio.run(rig.eng._run(rec.id))
        assert rig.eng.get(rec.id).state == JobState.DONE, rig.eng.get(rec.id)
        if member:
            assert seen["fsck"] is True and ".claude/settings.json" in seen["skip"]
        else:
            assert seen["fsck"] is False and seen["skip"] == ()


@pytest.mark.parametrize("past", [-120.0, 120.0])
def test_q2_an_answer_after_a_drop_gives_the_next_drop_a_fresh_window(rig, monkeypatch, past: float) -> None:
    from src.core.pack.jobs import store as store_mod

    monkeypatch.setattr(store_mod, "time", SimpleNamespace(time=rig.wall))
    rec = seed(rig, JobState.RUNNING, member=True)
    t0 = rig.mono.now
    st = {"phase": 0, "until": t0 + 200.0, "jumped": False}

    async def scripted(job_id: str) -> Any:
        rig.calls.append((C, "status"))
        if rig.mono.now < st["until"]:
            events = rig.eng.store.events(rec.id)
            if st["phase"] == 2 and not st["jumped"] and events[-1]["note"].startswith("waiting for "):
                st["jumped"] = True
                st["until"] = rig.mono.now + (60.0 if past < 0 else 1000.0)
                rig.wall.now = rig.eng.get(rec.id).updated_at + engine_run.COLLECT_WAIT_S + past
            raise JobError("unreachable", "down", 502)
        st["phase"] += 1
        if st["phase"] == 1:
            st["phase"], st["until"] = 2, rig.mono.now + 200.0
            return SimpleNamespace(state=HostState.RUNNING, exit_code=None, output_tail="", detail="")
        return SimpleNamespace(state=HostState.EXITED, exit_code=0, output_tail="", detail="")

    real_target = rig.eng._target_for

    def target_for(iid: str) -> Any:
        t = real_target(iid)
        t.status = scripted
        return t

    rig.eng._target_for = target_for
    asyncio.run(rig.eng._run(rec.id))
    notes = [e["note"] for e in rig.eng.store.events(rec.id)]
    assert st["jumped"] and any(n.endswith("answered again") for n in notes)
    assert sum(1 for n in notes if n.startswith("waiting for ")) == 2, "the second drop wrote a fresh waiting note"
    if past < 0:
        assert rig.eng.get(rec.id).state == JobState.DONE, notes
        assert not any(c[1] == "stop" for c in rig.calls)
    else:
        assert rig.eng.get(rec.id).state == JobState.LOST, notes


def test_q3_a_target_that_became_the_alpha_still_has_its_result_collected_and_a_removed_one_does_not(rig, monkeypatch) -> None:
    monkeypatch.setattr(member_reach, "member_ids_held", lambda: [D])
    monkeypatch.setattr(member_reach, "listed_ids_held", lambda: [C, D])
    rec = seed(rig, JobState.COLLECTING, member=True)
    asyncio.run(rig.eng._run(rec.id))
    assert rig.eng.get(rec.id).state == JobState.DONE and [c[1] for c in rig.calls].count("collect") == 1
    rig.calls.clear()
    monkeypatch.setattr(member_reach, "listed_ids_held", lambda: [D])
    gone = seed(rig, JobState.COLLECTING, member=True)
    asyncio.run(rig.eng._run(gone.id))
    assert rig.eng.get(gone.id).error_code == "peer_left" and not any(c[1] == "collect" for c in rig.calls)


def test_q3_a_running_job_whose_link_switch_went_off_is_not_peer_left(rig, monkeypatch) -> None:
    monkeypatch.setattr(member_reach, "member_ids_held", lambda: [D])
    monkeypatch.setattr(member_reach, "listed_ids_held", lambda: [C, D])
    back_at = rig.mono.now + 400.0

    def flap() -> None:
        if rig.mono.now < back_at:
            raise JobError("unreachable", "down", 502)

    rig.plan["status"] = flap
    rec = seed(rig, JobState.RUNNING, member=True)
    asyncio.run(rig.eng._run(rec.id))
    assert rig.eng.get(rec.id).state == JobState.DONE


def test_q4_a_jobs_own_carry_waits_on_an_unreadable_list_and_a_removed_computer_fails_at_once(rig, monkeypatch) -> None:
    async def connect(iid: str) -> Any:
        return None, "x"

    monkeypatch.setattr(member_link, "connect_for", connect)
    answers: List[Any] = [{"error": "member_list_unreadable"}, {"error": "member_list_unreadable"}, {"sent": True}]
    tries: List[int] = []

    async def carry(*_a: Any) -> Any:
        tries.append(1)
        return answers.pop(0)

    rig.eng._carry = carry
    asyncio.run(rig.eng._carry_commits(str(rig.root), UID, C))
    assert len(tries) == 3
    answers[:] = [{"error": "member_list_unreadable"}, {"error": "member_not_listed"}, {"sent": True}]
    tries.clear()
    with pytest.raises(JobError) as caught:
        asyncio.run(rig.eng._carry_commits(str(rig.root), UID, C))
    assert caught.value.code == "member_not_listed" and len(tries) == 2
    answers[:] = [{"error": "member_list_unreadable"}] * 500
    tries.clear()
    with pytest.raises(JobError) as caught:
        asyncio.run(rig.eng._carry_commits(str(rig.root), UID, C))
    assert caught.value.code == "member_list_unreadable" and len(tries) < 500, "the wait is bounded by lost_after_s"


def test_a_member_is_never_chosen_when_its_result_upload_would_be_refused(rig, monkeypatch) -> None:
    def ask(cmd: str) -> JobRecord:
        return asyncio.run(rig.eng.propose(dataclasses.replace(job(rig), command=cmd)))

    star = rule.MachineInput("iid-s", "s", rich(1.0, "iid-s"), True, False, False, True, None)
    star_view = PlaceView(rig.me, [star], {"iid-s": [CAP_JOBS]}, "iid-s", None)
    no_replica = restrictions_mod.Restrictions(may_host_agents=False, may_receive_projects=True)
    no_upload = restrictions_mod.Restrictions(may_host_agents=False, may_receive_projects=False)
    rig.eng._restrictions = restrictions_mod.Restrictions
    rec = ask("echo one")
    assert rec.state == JobState.WAITING_APPROVAL and rec.peer_install_id in (C, D) and rig.calls == [(rec.peer_install_id, "admit")]
    rig.calls.clear()
    rig.eng._restrictions = lambda: no_replica
    rec = ask("echo two")
    assert rec.state == JobState.HERE and "accept no uploads" in (rec.reason or "") and rig.calls == []
    rig.eng._view_for = lambda _r, _u: star_view
    rec = ask("echo three")
    assert rec.state == JobState.WAITING_APPROVAL and rec.peer_install_id == "iid-s" and rig.calls == [("iid-s", "admit")]
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    rig.calls.clear()
    assert ask("echo four").peer_install_id == "iid-s" and rig.calls == [("iid-s", "admit")]
    rig.calls.clear()
    rig.eng._restrictions = lambda: no_upload
    rec = ask("echo five")
    assert rec.state == JobState.HERE and "accept no uploads" in (rec.reason or "") and rig.calls == []

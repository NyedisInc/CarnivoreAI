
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException

from src.api import pack_jobs_needs_routes as needs_routes
from src.core.mcp import pack_jobs_tools as tools
from src.core.pack.jobs import agent_facts, engine as engine_mod, host_admit, needs_policy, policy as policy_mod
from src.core.pack.jobs.agent_types import CAP_AGENT
from src.core.pack.jobs.engine import Engine, idem_key
from src.core.pack.jobs.engine_agent import AgentRequest
from src.core.pack.jobs.place import PlaceView, place
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import CAP_JOBS, CAP_NEEDS, AdmitBody, JobError, JobRecord, JobRequest, JobState
from src.core.pack.placement import needs as needs_mod, rule
from src.core.pack.placement.needs import parse_need
from src.core.pack.placement.workload import resolve
from src.core.pack.reserve.holds import HOLDS, Holds

A, B, C = "iid-a", "iid-b", "iid-c"
UID = "p1x23456"
SUITE = resolve({"kind": "suite"})


def snap(load: float = 0.0, *, tools_: Optional[Dict[str, bool]] = None, can: bool = True, pegged: bool = False,
         why: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {"load": {"cores": 10, "busy_cores": load, "mem_total_gb": 32.0, "mem_available_gb": 28.0, "disk_free_gb": 200.0},
                           "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}, "toolchain": {}}
    if can:
        out["can"] = {"v": 1, "tools": dict(tools_ or {})}
    if pegged:
        out["pressure"] = {"pegged": True, "why": why or "busy cores over the line", "mem": "normal"}
    return out


def machine(iid: str, label: str, snapshot: Optional[Dict[str, Any]], *, is_self: bool = False, usable: bool = True) -> rule.MachineInput:
    return rule.MachineInput(iid, label, snapshot, usable, is_self, is_self, True, None)


def view(me: rule.MachineInput, *peers: rule.MachineInput) -> PlaceView:
    return PlaceView(me, list(peers), {p.install_id: [CAP_JOBS] for p in peers}, A)


@pytest.fixture()
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "state")


@pytest.fixture()
def pol(store: JobStore) -> policy_mod.Policy:
    policy_mod.set_auto(store, UID, True)
    return policy_mod.get(store, UID)


def projects_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE projects (uid TEXT, air_gap INTEGER)")
    return conn


def words(*w: str) -> List[needs_mod.Need]:
    return [parse_need(x) for x in w]




def test_here_when_this_computer_meets_the_needs_and_has_room_and_it_takes_a_hold(pol) -> None:
    got = place(SUITE, UID, pol, view(machine(A, "mac", snap(tools_={"ffmpeg": True}), is_self=True), machine(B, "tower", snap())),
                needs=words("ffmpeg"))
    assert got.decision == "here" and HOLDS.total()[0] == SUITE.est_cpu_cores


def test_remote_when_this_computer_lacks_the_need_and_a_target_has_it_with_room(pol) -> None:
    got = place(SUITE, UID, pol, view(machine(A, "mac", snap(), is_self=True), machine(B, "tower", snap(tools_={"xcode": True}))),
                needs=words("xcode"))
    assert (got.decision, got.peer_install_id) == ("remote", B) and HOLDS.total()[2] == 0


def test_here_at_once_when_nobody_has_room_but_this_computer_meets_the_needs(pol) -> None:
    got = place(SUITE, UID, pol, view(machine(A, "mac", snap(9.5, tools_={"ffmpeg": True}), is_self=True),
                                      machine(B, "tower", snap(9.5, tools_={"ffmpeg": True}))), needs=words("ffmpeg"))
    assert got.decision == "here" and "no other computer can take it now" in got.reason


def test_requirement_busy_names_the_computer_that_has_it_and_why_it_is_full(pol) -> None:
    got = place(SUITE, UID, pol, view(machine(A, "mac", snap(), is_self=True), machine(B, "tower", snap(9.5, tools_={"xcode": True}))),
                needs=words("xcode"))
    assert (got.decision, got.code) == ("refused", "requirement_busy")
    assert "tower" in got.reason and "full" in got.reason and "this computer" in got.reason


def test_requirement_unmet_names_each_computer_and_what_it_lacks(pol) -> None:
    got = place(SUITE, UID, pol, view(machine(A, "mac", snap(), is_self=True), machine(B, "tower", snap(tools_={"xcode": False})),
                                      machine(C, "old", snap(can=False))), needs=words("xcode"))
    assert (got.decision, got.code) == ("refused", "requirement_unmet")
    assert "tower lacks xcode" in got.reason and "old has not reported whether it has xcode (needs an app update)" in got.reason


def test_a_computer_that_would_meet_it_but_may_not_take_work_is_named_with_that_reason(pol) -> None:
    p = dataclasses.replace(pol, never_use=["tower"])
    got = place(SUITE, UID, p, view(machine(A, "mac", snap(), is_self=True), machine(B, "tower", snap(tools_={"xcode": True}))), needs=words("xcode"))
    assert got.code == "requirement_unmet" and "tower would meet it but is on the never use list" in got.reason


def test_a_target_filter_never_refuses_the_job_stays_here(pol) -> None:
    got = place(SUITE, UID, pol, view(machine(A, "mac", snap(9.5), is_self=True), machine(B, "tower", snap(tools_={"playwright_browsers": False}))),
                filters=words("playwright_browsers"))
    assert got.decision == "here" and got.code is None


def test_a_preference_orders_candidates_and_never_moves_work_off_a_computer_with_room(pol) -> None:
    mine = machine(A, "mac", snap(), is_self=True)
    assert place(SUITE, UID, pol, view(mine, machine(B, "tower", snap(tools_={"ffmpeg": True}))), prefer=words("ffmpeg")).decision == "here"
    busy = machine(A, "mac", snap(9.5), is_self=True)
    got = place(SUITE, UID, pol, view(busy, machine(B, "plain", snap()), machine(C, "fast", snap(tools_={"ffmpeg": True}))), prefer=words("ffmpeg"))
    assert got.peer_install_id == C


def test_the_mark_off_answers_here_whatever_is_needed(store) -> None:
    got = place(SUITE, UID, policy_mod.get(store, UID), view(machine(A, "mac", snap(), is_self=True)), needs=words("xcode"))
    assert got.decision == "here" and got.reason == "project is set to this computer only"


def test_a_burst_of_five_calls_on_a_computer_with_room_for_two_stays_twice_then_leaves(pol) -> None:
    v = view(machine(A, "mac", snap(), is_self=True), machine(B, "tower", snap()))
    answers = [place(SUITE, UID, pol, v).decision for _ in range(5)]
    assert answers == ["here", "remote", "remote", "remote", "remote"]
    legacy_holds = Holds()
    legacy = [place(SUITE, UID, pol, v, holds=legacy_holds, active_balance=False).decision for _ in range(5)]
    assert legacy == ["here", "here", "here", "remote", "remote"]


def test_this_computer_pegged_sends_work_away_even_when_the_figures_say_room(pol) -> None:
    got = place(SUITE, UID, pol, view(machine(A, "mac", snap(pegged=True), is_self=True), machine(B, "tower", snap())))
    assert got.decision == "remote"




class FakeTarget:

    install_id, label = B, "tower"

    def __init__(self) -> None:
        self.admitted: List[AdmitBody] = []
        self.refuse: Optional[JobError] = None

    async def admit(self, body: AdmitBody) -> None:
        self.admitted.append(body)
        if self.refuse is not None:
            raise self.refuse


def make_engine(tmp_path: Path, the_view: PlaceView, monkeypatch: pytest.MonkeyPatch, target: FakeTarget) -> Engine:
    state, jobs = tmp_path / "state", tmp_path / "jobs"
    state.mkdir()
    jobs.mkdir()

    async def facts(_s: Optional[str]) -> agent_facts.CallerFacts:
        return agent_facts.CallerFacts("claude", "work", "default", "m", None)

    eng = Engine(state_dir=state, jobs_root=jobs, install_id=A, target_for=lambda _i: target, open_db=projects_db,
                 view_for=lambda _r, _u: the_view, facts_for=facts)
    monkeypatch.setattr(eng, "_resolve_project", lambda folder: ({"uid": UID, "name": "app", "root": folder}, ""))
    return eng


def no_snapshot(*_a: Any, **_k: Any) -> Any:
    raise AssertionError("a refused job must never take a snapshot")


def mark(eng: Engine) -> None:
    policy_mod.set_auto(eng.store, UID, True)


def test_a_refused_job_is_one_terminal_row_with_the_code_and_no_snapshot(tmp_path, monkeypatch) -> None:
    eng = make_engine(tmp_path, view(machine(A, "mac", snap(), is_self=True), machine(B, "tower", snap())), monkeypatch, FakeTarget())
    monkeypatch.setattr(engine_mod.snapshot, "take", no_snapshot)
    mark(eng)
    rec = asyncio.run(eng.propose(JobRequest(command="xcodebuild test", folder=str(tmp_path), kind="build")))
    assert rec.state == JobState.REFUSED and rec.error_code == "requirement_unmet" and "xcode" in (rec.reason or "")
    assert rec.snapshot_commit is None and eng.store.find_live_by_idem(rec.idem_key) is None


def test_an_agent_job_gets_the_same_ladder_as_a_command_job(tmp_path, monkeypatch) -> None:
    the_view = PlaceView(machine(A, "mac", snap(), is_self=True), [machine(B, "tower", snap())], {B: [CAP_JOBS, CAP_AGENT]}, A)
    eng = make_engine(tmp_path, the_view, monkeypatch, FakeTarget())
    monkeypatch.setattr(engine_mod.snapshot, "take", no_snapshot)
    mark(eng)
    req = AgentRequest(command="", folder=str(tmp_path), kind="build", caller_session="ses_x", task="build the app", needs=["xcode"])
    rec = asyncio.run(eng.propose(req))
    assert rec.state == JobState.REFUSED and rec.error_code == "requirement_unmet" and rec.body == "agent"


def test_the_program_names_in_a_command_are_strict_needs_and_a_project_document_adds_its_own(tmp_path, monkeypatch) -> None:
    eng = make_engine(tmp_path, view(machine(A, "mac", snap(), is_self=True)), monkeypatch, FakeTarget())
    mark(eng)
    needs_policy.put(eng.store, UID, {"build": {"needs": ["gpu:nvidia"], "prefer": []}})
    asks = needs_policy.merge(eng.store, UID, JobRequest(command="npx playwright test && ffmpeg -i a b", folder="/w", kind="build", needs=["xcode"]))
    assert [n.text for n in asks.strict] == ["xcode", "gpu:nvidia", "node", "ffmpeg"]
    assert [n.text for n in asks.filters] == ["playwright_browsers"]


def test_a_stored_document_replaces_the_kinds_defaults(store) -> None:
    req = JobRequest(command="pytest -q", folder="/w", kind="browser")
    assert [n.text for n in needs_policy.merge(store, UID, req).filters] == ["playwright_browsers"]
    needs_policy.put(store, UID, {"browser": {"needs": [], "prefer": []}})
    assert needs_policy.merge(store, UID, req).filters == ()
    needs_policy.put(store, UID, {"browser": None})
    assert [n.text for n in needs_policy.merge(store, UID, req).filters] == ["playwright_browsers"]
    needs_policy.put(store, UID, {"render": {"needs": ["gpu:nvidia"], "prefer": ["ffmpeg"]}})
    assert needs_policy.get(store, UID, "render") == (["gpu:nvidia"], ["ffmpeg"])


def test_the_stored_document_refuses_unknown_kinds_words_and_extra_keys(store) -> None:
    for bad in ({"nope": {"needs": []}}, {"render": {"needs": ["warp drive"]}}, {"render": {"colour": []}}, {"render": {"needs": ["gpu"] * 9}}, []):
        with pytest.raises(ValueError):
            needs_policy.put(store, UID, bad)  # type: ignore[arg-type]


def test_the_admit_body_is_todays_body_without_needs_and_an_older_peer_is_never_sent_them(tmp_path, monkeypatch) -> None:
    body = AdmitBody(job_id="job_0123456789ab", project_uid="uid-test-0001", kind="suite")
    assert body.model_dump() == {"job_id": "job_0123456789ab", "project_uid": "uid-test-0001", "kind": "suite", "est_cpu": None, "est_ram_gb": None}
    assert AdmitBody(job_id="job_0123456789ab", project_uid="uid-test-0001", kind="suite", needs=["ffmpeg"]).model_dump()["needs"] == ["ffmpeg"]
    with pytest.raises(ValueError):
        AdmitBody(job_id="job_0123456789ab", project_uid="uid-test-0001", kind="suite", needs=["warp drive"])
    for caps, expect in (([CAP_JOBS], None), ([CAP_JOBS, CAP_NEEDS], ["ffmpeg"])):
        target = FakeTarget()
        the_view = PlaceView(machine(A, "mac", snap(9.5), is_self=True), [machine(B, "tower", snap(tools_={"ffmpeg": True}))], {B: caps}, A)
        (tmp_path / str(len(caps))).mkdir()
        eng = make_engine(tmp_path / str(len(caps)), the_view, monkeypatch, target)
        mark(eng)
        monkeypatch.setattr(engine_mod, "scopes_for", lambda *a, **k: {"replica"})
        monkeypatch.setattr(engine_mod.snapshot, "take", lambda *a, **k: (_ for _ in ()).throw(JobError("snapshot_too_large", "x")))
        asyncio.run(eng.propose(JobRequest(command="ffmpeg -i a b", folder=str(tmp_path), kind="build")))
        assert target.admitted and target.admitted[0].needs == expect


def test_a_host_refusal_replaces_once_and_the_reason_keeps_the_refusal(tmp_path, monkeypatch) -> None:
    target = FakeTarget()
    target.refuse = JobError("lacks_tool", "this computer lacks xcode", 409)
    the_view = PlaceView(machine(A, "mac", snap(9.5), is_self=True), [machine(B, "tower", snap(tools_={"xcode": True}))], {B: [CAP_JOBS, CAP_NEEDS]}, A)
    eng = make_engine(tmp_path, the_view, monkeypatch, target)
    mark(eng)
    monkeypatch.setattr(engine_mod, "scopes_for", lambda *a, **k: {"replica"})
    monkeypatch.setattr(engine_mod.snapshot, "take", no_snapshot)
    rec = asyncio.run(eng.propose(JobRequest(command="xcodebuild test", folder=str(tmp_path), kind="build")))
    assert rec.state == JobState.REFUSED and "tower this computer lacks xcode" in (rec.reason or "") and len(target.admitted) == 1




def test_the_key_is_phase_ones_literal_without_needs_and_differs_with_them() -> None:
    req = JobRequest(command="pytest -q", folder="/w/app", caller_session="ses_a", outputs=["b", "a"])
    assert idem_key(req) == "c2f1fbc4cc5f9431e2f5e304439b51b7b21f0a93ead254e16bbe46d3772e533c"
    assert idem_key(dataclasses.replace(req, needs=["xcode"])) != idem_key(req)
    assert idem_key(dataclasses.replace(req, prefer=["gpu"])) != idem_key(req)
    assert idem_key(dataclasses.replace(req, needs=["xcode"])) == idem_key(dataclasses.replace(req, needs=["xcode"]))


def test_request_validation_names_the_known_words() -> None:
    with pytest.raises(JobError) as exc:
        JobRequest(command="ls", folder="/w", needs=["warp drive"]).validate()
    assert exc.value.code == "bad_request" and "known words" in exc.value.detail
    with pytest.raises(JobError):
        JobRequest(command="ls", folder="/w", prefer=["gpu"] * 9).validate()
    JobRequest(command="ls", folder="/w", needs=["xcode", "mem_gb>=32", "label:render box"], prefer=["gpu:nvidia"]).validate()




def fake_host(tmp_path: Path, room: float) -> Any:
    store = JobStore(tmp_path / "hs")
    store.policy_row("created")
    return SimpleNamespace(store=store, _admit=lambda work: None if work.est_cpu_cores <= room else "this computer is busy")


def admit_body(job_id: str, **extra: Any) -> AdmitBody:
    return AdmitBody(job_id=job_id, project_uid="uid-test-0001", kind="suite", **extra)


def test_the_target_rechecks_the_needs_against_its_own_probe(tmp_path, monkeypatch) -> None:
    host = fake_host(tmp_path, 10)
    monkeypatch.setattr(host_admit, "own_snapshot", lambda: snap(tools_={"ffmpeg": True}))
    host_admit.admit(host, A, admit_body("job_000000000001", needs=["ffmpeg"]), SUITE)
    with pytest.raises(JobError) as exc:
        host_admit.admit(host, A, admit_body("job_000000000002", needs=["xcode"]), SUITE)
    assert exc.value.code == "lacks_tool" and "xcode" in exc.value.detail
    monkeypatch.setattr(host_admit, "own_snapshot", lambda: None)
    with pytest.raises(JobError) as exc:
        host_admit.admit(host, A, admit_body("job_000000000003", needs=["ffmpeg"]), SUITE)
    assert exc.value.code == "lacks_tool"
    host_admit.admit(host, A, admit_body("job_000000000004"), SUITE)


def test_the_target_refuses_while_pegged_and_the_refusal_holds_nothing(tmp_path, monkeypatch) -> None:
    host = fake_host(tmp_path, 10)
    monkeypatch.setattr(host_admit, "own_snapshot", lambda: snap(pegged=True, why="memory pressure"))
    with pytest.raises(JobError) as exc:
        host_admit.admit(host, A, admit_body("job_000000000001"), SUITE)
    assert exc.value.code == "pegged" and "memory pressure" in exc.value.detail and HOLDS.total()[2] == 0


def test_two_callers_admitting_at_once_on_one_target_one_is_held_and_one_refused(tmp_path, monkeypatch) -> None:
    host = fake_host(tmp_path, 5)
    monkeypatch.setattr(host_admit, "own_snapshot", lambda: snap())
    barrier, results = threading.Barrier(2), []

    def go(caller: str, job_id: str) -> None:
        barrier.wait()
        try:
            host_admit.admit(host, caller, admit_body(job_id), SUITE)
            results.append("held")
        except JobError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=go, args=(c, j)) for c, j in ((B, "job_000000000001"), (C, "job_000000000002"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["held", "host_busy"]


def test_start_counts_every_other_hold_and_runner_start_shortens_its_own(tmp_path, monkeypatch) -> None:
    host = fake_host(tmp_path, 5)
    monkeypatch.setattr(host_admit, "own_snapshot", lambda: snap())
    host_admit.admit(host, B, admit_body("job_000000000001"), SUITE)
    host_admit.start_hold(host, B, "job_000000000001", "uid-test-0001", SUITE)
    with pytest.raises(JobError) as exc:
        host_admit.start_hold(host, C, "job_000000000002", "uid-test-0001", SUITE)
    assert exc.value.code == "host_busy"
    host_admit.drop("job_000000000001")
    host_admit.start_hold(host, C, "job_000000000002", "uid-test-0001", SUITE)
    host_admit.runner_started("job_000000000002")
    assert HOLDS.total()[2] == 1


def test_the_capability_is_registered_so_an_old_peer_never_looks_like_it_has_it() -> None:
    from src.core.pack.machines import capabilities

    assert CAP_NEEDS == "pack.jobs.needs" and CAP_NEEDS in capabilities.names()




def test_the_delegate_description_stays_short_and_the_new_arguments_carry_the_words() -> None:
    description, props, _required, _fn = tools.WRITE_TOOLS["delegate"]
    assert len(description) < 400 and {"needs", "prefer"} <= set(props)
    assert "xcode" in props["needs"]["description"] and props["prefer"]["maxItems"] == 8


def test_the_tool_checks_the_words_and_answers_a_refusal_as_decision_refused() -> None:
    with pytest.raises(tools.ToolError) as exc:
        tools._wishes({"needs": ["warp drive"]})
    assert "known words" in str(exc.value)
    assert tools._wishes({"needs": ["XCODE"], "prefer": None}) == {"needs": ["xcode"], "prefer": []}
    rec = JobRecord(id="job_0123456789ab", state=JobState.REFUSED, error_code="requirement_busy", error_detail="tower has xcode but is full")
    assert tools.agent_result(rec) == {"decision": "refused", "code": "requirement_busy", "reason": "tower has xcode but is full"}
    assert JobState.REFUSED in tools.TERMINAL




def test_the_needs_routes_round_trip_and_name_the_vocabulary(store, monkeypatch) -> None:
    monkeypatch.setattr(needs_routes, "_uid", lambda name: UID)
    monkeypatch.setattr(needs_routes.boot, "engine", lambda: SimpleNamespace(store=store))
    got = asyncio.run(needs_routes.get_delegate_needs("app"))
    assert got["kinds"]["browser"] == {"needs": [], "prefer": [], "stored": False, "default_filters": ["playwright_browsers"], "default_prefer": []}
    assert got["kinds"]["render"]["default_prefer"] == ["gpu", "ffmpeg"] and "xcode" in got["vocabulary"]
    put = asyncio.run(needs_routes.put_delegate_needs("app", {"render": {"needs": ["gpu:nvidia"], "prefer": []}}))
    assert put["kinds"]["render"]["needs"] == ["gpu:nvidia"] and put["kinds"]["render"]["stored"] is True
    gone = asyncio.run(needs_routes.put_delegate_needs("app", {"render": None}))
    assert gone["kinds"]["render"]["stored"] is False
    with pytest.raises(HTTPException) as exc:
        asyncio.run(needs_routes.put_delegate_needs("app", {"render": {"needs": ["warp drive"]}}))
    assert exc.value.status_code == 422 and exc.value.detail["code"] == "bad_needs"

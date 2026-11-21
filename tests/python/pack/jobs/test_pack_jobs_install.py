
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import stat
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.api import federation_pack_install_routes as routes
from src.core.pack.jobs import engine as engine_mod, install as inst, policy as policy_mod
from src.core.pack.jobs.engine import Engine
from src.core.pack.jobs.engine_run import HOST_REFUSALS, load_ctx
from src.core.pack.jobs.install import ALLOW, CAP_INSTALL, Installer
from src.core.pack.jobs.place import PlaceView, install_candidates, place
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import CAP_JOBS, CAP_NEEDS, AdmitBody, JobError, JobRecord, JobRequest, JobState
from src.core.pack.machines import restrictions as restrictions_mod
from src.core.pack.placement import rule
from src.core.pack.placement.needs import parse_need
from src.core.pack.placement.workload import resolve

A, B, C = "iid-a", "iid-b", "iid-c"
UID = "p1x23456"
JOB = "job_0123456789ab"
SUITE = resolve({"kind": "build"})


def snap(*, tools_: Optional[Dict[str, bool]] = None, brew: bool = True, install: bool = True, load: float = 0.0) -> Dict[str, Any]:
    return {"load": {"cores": 10, "busy_cores": load, "mem_total_gb": 32.0, "mem_available_gb": 28.0, "disk_free_gb": 200.0},
            "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}, "toolchain": {},
            "can": {"v": 1, "brew": brew, "tools": dict(tools_ or {})}, "restrictions": {"may_install_tools": install}}


def machine(iid: str, label: str, snapshot: Optional[Dict[str, Any]], *, is_self: bool = False) -> rule.MachineInput:
    return rule.MachineInput(iid, label, snapshot, True, is_self, is_self, True, None)


def view(me: rule.MachineInput, *peers: rule.MachineInput, caps: Optional[List[str]] = None) -> PlaceView:
    return PlaceView(me, list(peers), {p.install_id: caps if caps is not None else [CAP_JOBS, CAP_INSTALL] for p in peers}, A)


@pytest.fixture()
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "state")


@pytest.fixture()
def pol(store: JobStore) -> policy_mod.Policy:
    policy_mod.set_auto(store, UID, True)
    return policy_mod.get(store, UID)


def fake_brew(tmp_path: Path, body: str) -> str:
    path = tmp_path / "brew"
    path.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{tmp_path}/argv.txt"\nenv | cut -d= -f1 | sort > "{tmp_path}/envnames.txt"\n{body}\n')
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def installer(store: JobStore, tmp_path: Path, brew: Optional[str], *, switch: bool = True, **kw: Any) -> Installer:
    kw.setdefault("present", lambda _tool: False)
    return Installer(store, tmp_path / "jobs", brew=lambda: brew, restrictions=lambda: restrictions_mod.Restrictions(may_install_tools=switch), **kw)


async def settle(ins: Installer) -> None:
    while ins._tasks:
        await asyncio.gather(*list(ins._tasks))




def test_the_allow_list_is_exactly_the_six_names_and_names_no_container_tool_cask_or_tap() -> None:
    assert ALLOW == {"ffmpeg": "ffmpeg", "ffprobe": "ffmpeg", "node": "node", "npm": "node", "gh": "gh", "python3.12": "python@3.12"}
    for name, formula in ALLOW.items():
        text = f"{name} {formula}".lower()
        assert not any(bad in text for bad in ("docker", "colima", "orbstack", "podman", "cask", "/", "tap", "git", "tmux"))
    assert inst.formulas_of(["ffmpeg", "ffprobe", "npm"]) == ["ffmpeg", "node"] and inst.covered(["ffmpeg"]) == ["ffmpeg", "ffprobe"]


def test_brew_runs_by_absolute_path_with_a_fixed_argv_and_a_built_environment(store, tmp_path) -> None:
    brew = fake_brew(tmp_path, "exit 0")
    ins = installer(store, tmp_path, brew, owns_job=lambda j, c: True)

    async def flow() -> List[inst.InstallRow]:
        rows = await ins.request("peer-a", JOB, ["ffprobe", "ffmpeg"])
        await settle(ins)
        return rows

    rows = asyncio.run(flow())
    assert len(rows) == 1
    assert (tmp_path / "argv.txt").read_text().split() == ["install", "--formula", "ffmpeg"]
    names = set((tmp_path / "envnames.txt").read_text().split())
    expect = {"HOME", "LANG", "PATH", *inst.BREW_FLAGS}
    assert expect <= names and names - expect - {"USER", "PWD", "SHLVL", "_", "OLDPWD"} == set()
    assert store.install_get(rows[0].id).state == "done"
    log = tmp_path / "jobs" / "installs" / f"{rows[0].id}.log"
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_a_name_outside_the_allow_list_never_reaches_a_command(store, tmp_path) -> None:
    ins = installer(store, tmp_path, fake_brew(tmp_path, "exit 0"), owns_job=lambda j, c: True)
    for bad in (["docker"], ["ffmpeg; rm -rf /"], ["--cask", "blender"], ["git"], ["tmux"], [], ["ffmpeg"] * 7, [3]):
        with pytest.raises(JobError) as err:
            asyncio.run(ins.request("peer-a", JOB, bad))  # type: ignore[arg-type]
        assert err.value.code == "tool_not_allowed"
    assert not (tmp_path / "argv.txt").exists()


def test_the_owners_switch_off_refuses_and_no_homebrew_is_a_plain_refusal(store, tmp_path) -> None:
    brew = fake_brew(tmp_path, "exit 0")
    with pytest.raises(JobError) as err:
        asyncio.run(installer(store, tmp_path, brew, switch=False, owns_job=lambda j, c: True).request("peer-a", JOB, ["gh"]))
    assert (err.value.code, err.value.status) == ("pack_restricted", 403)
    with pytest.raises(JobError) as err:
        asyncio.run(installer(store, tmp_path, None, owns_job=lambda j, c: True).request("peer-a", JOB, ["gh"]))
    assert err.value.code == "no_brew" and not (tmp_path / "argv.txt").exists()


def test_a_job_the_caller_holds_nothing_for_is_unknown_and_a_sixth_install_a_day_is_refused(store, tmp_path) -> None:
    ins = installer(store, tmp_path, fake_brew(tmp_path, "exit 0"), owns_job=lambda j, c: (j, c) == (JOB, "peer-a"))
    with pytest.raises(JobError) as err:
        asyncio.run(ins.request("peer-b", JOB, ["gh"]))
    assert err.value.code == "unknown_job"

    async def five() -> None:
        for n in range(5):
            store.install_put(inst.InstallRow(id=f"ins_00000000000{n}", tool="gh", formula="gh", caller_install="peer-a", job_id=f"x{n}",
                                              state="done", started_at=time.time()))
        with pytest.raises(JobError) as limit:
            await ins.request("peer-a", JOB, ["gh"])
        assert limit.value.code == "install_limit"

    asyncio.run(five())


def test_a_timeout_kills_the_whole_process_group(tmp_path) -> None:
    pid_file = tmp_path / "child.pid"
    brew = fake_brew(tmp_path, f'sleep 60 &\necho $! > "{pid_file}"\nwait')
    t0 = time.time()
    code, tail = inst.run_brew([brew, "install", "--formula", "ffmpeg"], inst.brew_env(), tmp_path / "x.log", 1.0)
    assert code == 124 and "timed out" in tail and time.time() - t0 < 20
    child = int(pid_file.read_text())
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


def test_one_install_runs_at_a_time_and_a_finished_one_reprobes(store, tmp_path) -> None:
    running, peak, lock = [0], [0], threading.Lock()
    probed: List[str] = []
    shown: List[Optional[str]] = []

    def slow(argv: List[str], env: Dict[str, str], log: Path, timeout: float) -> Any:
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.15)
        with lock:
            running[0] -= 1
        return (1, "boom") if argv[-1] == "gh" else (0, "")

    ins = installer(store, tmp_path, "/fake/brew", owns_job=lambda j, c: True, run_proc=slow, on_done=lambda: probed.append("probe"),
                    on_installing=shown.append)

    async def flow() -> None:
        await asyncio.gather(ins.request("peer-a", JOB, ["ffmpeg"]), ins.request("peer-a", "job_aaaaaaaaaaaa", ["node"]))
        await settle(ins)
        await ins.request("peer-a", "job_bbbbbbbbbbbb", ["gh"])
        await settle(ins)

    asyncio.run(flow())
    assert peak[0] == 1 and probed
    assert shown[-1] is None and {"ffmpeg", "node", "gh"} <= set(shown)
    states = {r.tool: (r.state, r.exit_code, r.tail) for r in store.install_list()}
    assert states["gh"] == ("failed", 1, "boom") and states["ffmpeg"][0] == "done"


def test_a_restart_fails_an_install_it_cut_off(store, tmp_path) -> None:
    store.install_put(inst.InstallRow(id="ins_000000000001", tool="gh", formula="gh", state="running", started_at=time.time()))
    assert installer(store, tmp_path, None).recover() == 1
    assert store.install_get("ins_000000000001").state == "failed"


def test_the_public_row_never_carries_a_formula() -> None:
    row = inst.InstallRow(id="ins_000000000002", tool="python3.12", formula="python@3.12", caller_install="peer-a")
    assert "formula" not in row.public() and "python@3.12" not in json.dumps(row.public())




def test_the_peer_route_body_is_strict_and_the_capability_is_advertised() -> None:
    from src.core.pack.machines import capabilities

    assert CAP_INSTALL == "pack.jobs.install" and CAP_INSTALL in capabilities.names()
    with pytest.raises(ValueError):
        routes.InstallBody(job_id="job_0123456789ab", project_uid="p", tools=["gh"], formula="x")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        routes.InstallBody(job_id="not-a-job", project_uid="p", tools=["gh"])
    assert routes.router.prefix == "/federation/pack/jobs/install"




def lacking(**kw: Any) -> Dict[str, Any]:
    return snap(tools_={"ffmpeg": False}, **kw)


def test_a_computer_that_can_install_it_is_offered_with_the_tools_named(pol) -> None:
    got = place(SUITE, UID, pol, view(machine(A, "mac", snap(), is_self=True), machine(B, "tower", lacking())), needs=[parse_need("ffmpeg"), parse_need("ffprobe")])
    assert (got.decision, got.peer_install_id, got.install) == ("remote", B, ["ffmpeg"]) and "Homebrew" in got.reason


@pytest.mark.parametrize("target,caps", [
    (lacking(brew=False), None),
    (lacking(install=False), None),
    (lacking(), [CAP_JOBS]),
    (snap(tools_={"xcode": False}), None),
])
def test_no_install_candidate_without_brew_the_switch_the_capability_or_an_installable_tool(pol, target, caps) -> None:
    need = "xcode" if "xcode" in target["can"]["tools"] else "ffmpeg"
    got = place(SUITE, UID, pol, view(machine(A, "mac", snap(), is_self=True), machine(B, "tower", target), caps=caps), needs=[parse_need(need)])
    assert (got.decision, got.code, got.install) == ("refused", "requirement_unmet", [])


def test_a_target_lacking_an_installable_and_a_non_installable_tool_is_not_offered(pol) -> None:
    got = place(SUITE, UID, pol, view(machine(A, "mac", snap(), is_self=True), machine(B, "tower", snap(tools_={"ffmpeg": False, "xcode": False}))),
                needs=[parse_need("ffmpeg"), parse_need("xcode")])
    assert got.decision == "refused"


def test_a_computer_that_already_has_it_wins_and_installs_nothing(pol) -> None:
    got = place(SUITE, UID, pol, view(machine(A, "mac", snap(), is_self=True), machine(B, "tower", lacking()), machine(C, "box", snap(tools_={"ffmpeg": True}))),
                needs=[parse_need("ffmpeg")])
    assert (got.decision, got.peer_install_id, got.install) == ("remote", C, [])


def test_this_computer_never_installs_on_itself_and_a_full_candidate_is_not_picked(pol) -> None:
    me = machine(A, "mac", lacking(), is_self=True)
    assert place(SUITE, UID, pol, view(me), needs=[parse_need("ffmpeg")]).install == []
    assert install_candidates(SUITE, UID, pol, view(me, machine(B, "tower", lacking(load=9.5))), needs=[parse_need("ffmpeg")]) is None




class FakeTarget:

    install_id, label = B, "tower"

    def __init__(self, states: Optional[List[str]] = None, *, exit_code: int = 1) -> None:
        self.admitted: List[AdmitBody] = []
        self.installed: List[Any] = []
        self.states = states or ["running", "done"]
        self.exit_code = exit_code

    async def admit(self, body: AdmitBody) -> None:
        self.admitted.append(body)

    async def install(self, job_id: str, project_uid: str, tools: List[str]) -> List[Dict[str, Any]]:
        self.installed.append((job_id, project_uid, tools))
        return [{"id": "ins_000000000009", "tool": tools[0], "state": "queued"}]

    async def install_status(self, install_id: str) -> Dict[str, Any]:
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {"id": install_id, "tool": "ffmpeg", "state": state, "exit_code": self.exit_code if state == "failed" else 0,
                "tail": "Error: no bottle" if state == "failed" else ""}


def make_engine(tmp_path: Path, the_view: PlaceView, monkeypatch: pytest.MonkeyPatch, target: FakeTarget) -> Engine:
    state, jobs = tmp_path / "state", tmp_path / "jobs"
    state.mkdir()
    jobs.mkdir()
    eng = Engine(state_dir=state, jobs_root=jobs, install_id=A, target_for=lambda _i: target, open_db=lambda: sqlite3.connect(":memory:"),
                 view_for=lambda _r, _u: the_view)
    monkeypatch.setattr(eng, "_resolve_project", lambda folder: ({"uid": UID, "name": "app", "root": folder}, ""))

    async def fast(_s: float) -> None:
        await asyncio.sleep(0)

    eng._sleep = fast
    return eng


def test_the_install_is_stored_on_the_job_and_the_admit_body_leaves_the_tool_out(tmp_path, monkeypatch) -> None:
    target = FakeTarget()
    the_view = PlaceView(machine(A, "mac", snap(), is_self=True), [machine(B, "tower", lacking())], {B: [CAP_JOBS, CAP_NEEDS, CAP_INSTALL]}, A)
    eng = make_engine(tmp_path, the_view, monkeypatch, target)
    policy_mod.set_auto(eng.store, UID, True)
    fake = SimpleNamespace(commit="c" * 40, tree="t" * 40, taken_at=1.0, scope="", toplevel=str(tmp_path), head="h" * 40, notes=[], dep_dirs=[])
    monkeypatch.setattr(engine_mod.snapshot, "take", lambda *a, **k: fake)
    monkeypatch.setattr(engine_mod, "scopes_for", lambda *a, **k: {"replica"})
    rec = asyncio.run(eng.propose(JobRequest(command="ffmpeg -i a b", folder=str(tmp_path), kind="build")))
    assert rec.state == JobState.WAITING_APPROVAL and load_ctx(rec)["install"] == ["ffmpeg"]
    assert target.admitted[0].needs is None or "ffmpeg" not in target.admitted[0].needs
    from src.core.mcp import pack_jobs_tools as tools

    shown = tools._card({}, JobRequest(command="ffmpeg -i a b", folder=str(tmp_path), kind="build"), rec)
    assert shown["installs"] == ["ffmpeg"]
    again = asyncio.run(eng._refresh(rec))
    assert load_ctx(again)["install"] == ["ffmpeg"]


def waiting_job(eng: Engine, tools: List[str]) -> JobRecord:
    ctx = {"request": {"command": "ffmpeg -i a b", "folder": "/w", "kind": "build"}, "install": tools, "snap": {}}
    return eng.store.create_job(JobRecord(id=JOB, idem_key="k", project_uid=UID, project_name="app", request_json=json.dumps(ctx), state=JobState.MIRRORING,
                                          peer_install_id=B, peer_label="tower", created_at=time.time(), updated_at=time.time()))


def test_the_job_waits_for_the_install_shows_a_line_and_moves_on(tmp_path, monkeypatch) -> None:
    target = FakeTarget(["running", "running", "done"])
    eng = make_engine(tmp_path, PlaceView(machine(A, "mac", snap(), is_self=True), []), monkeypatch, target)
    rec = waiting_job(eng, ["ffmpeg"])
    asyncio.run(eng._install_first(rec, ["ffmpeg"]))
    assert target.installed == [(JOB, UID, ["ffmpeg"])]
    notes = [e["note"] for e in eng.store.events(JOB)]
    assert any(n.startswith("installing ffmpeg on tower with Homebrew, started ") for n in notes)


def test_a_failed_install_is_a_refusal_with_the_exit_code_and_the_log_line_so_the_job_ends_here(tmp_path, monkeypatch) -> None:
    target = FakeTarget(["failed"], exit_code=1)
    eng = make_engine(tmp_path, PlaceView(machine(A, "mac", snap(), is_self=True), []), monkeypatch, target)
    waiting_job(eng, ["ffmpeg"])

    async def run() -> JobRecord:
        await eng._run(JOB)
        return eng.store.get_job(JOB)

    done = asyncio.run(run())
    assert "install_failed" in HOST_REFUSALS and done.state == JobState.HERE
    assert done.error_code == "install_failed" and "exit 1" in done.error_detail and "no bottle" in done.error_detail

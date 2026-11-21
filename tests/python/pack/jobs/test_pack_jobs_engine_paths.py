
from __future__ import annotations

import asyncio
import dataclasses
import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from src.core.pack.jobs import bundle_io, engine_run, folders, guards, land, paths, policy as policy_mod
from src.core.pack.jobs.engine import Engine
from src.core.pack.jobs.host import Host, _replace_roots, _uninterruptible
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import CollectAnswer, HostState, JobError, JobRecord, JobRequest, JobState, RunStatus

UID = "uid-test-0001"


class FakeTarget:

    install_id, label = "iid-b", "b"

    def __init__(self) -> None:
        self.calls: List[tuple] = []
        self.plan: Dict[str, Any] = {}

    def _go(self, verb: str, *args: Any) -> None:
        self.calls.append((verb, *args))
        todo = self.plan.get(verb)
        if isinstance(todo, list):
            todo = todo.pop(0) if todo else None
        if todo is not None:
            raise todo

    async def admit(self, body: Any) -> None:
        self._go("admit")

    async def start(self, body: Any) -> str:
        self._go("start", body)
        return "preparing"

    async def status(self, job_id: str) -> RunStatus:
        self._go("status")
        return RunStatus(state=HostState.RUNNING)

    async def collect(self, job_id: str) -> CollectAnswer:
        self._go("collect")
        return CollectAnswer()

    async def stop(self, job_id: str, keep_files: bool) -> None:
        self._go("stop", keep_files)

    async def release(self, job_id: str) -> None:
        self._go("release")

    async def send_bundle(self, path: str) -> str:
        self._go("send_bundle")
        return "blob-1"


class Clock:

    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def rig(tmp_path):
    target, clock, spawned = FakeTarget(), Clock(), []

    def spawn(coro):
        spawned.append(coro.cr_frame.f_locals.get("job_id"))
        coro.close()
        return asyncio.get_event_loop().create_future()

    async def no_sleep(_s: float) -> None:
        await asyncio.sleep(0)

    state, jobs = tmp_path / "state", tmp_path / "jobs"
    state.mkdir()
    jobs.mkdir()
    carried: List[tuple] = []

    async def carry(root: str, uid: str, peer: str) -> None:
        carried.append((root, uid, peer))

    db_file = tmp_path / "projects.db"
    with closing(sqlite3.connect(db_file)) as conn:
        conn.execute("CREATE TABLE projects (uid TEXT PRIMARY KEY, air_gap INTEGER)")
        conn.execute("INSERT INTO projects VALUES (?, 0)", (UID,))
        conn.commit()
    eng = Engine(state_dir=state, jobs_root=jobs, install_id="iid-a", target_for=lambda _i: target, spawn=spawn, clock=clock, sleep=no_sleep,
                 carry_commits=carry, open_db=lambda: sqlite3.connect(db_file))
    eng.db_file = db_file  # type: ignore[attr-defined]
    eng.target, eng.clock, eng.spawned, eng.carried = target, clock, spawned, carried  # type: ignore[attr-defined]
    return eng


def seed(eng: Engine, state: JobState, *, age: float = 0.0, head: Optional[str] = None) -> JobRecord:
    now = eng.clock() - age  # type: ignore[attr-defined]
    req = JobRequest(command="echo hi", folder="/work/app")
    ctx = {"request": dataclasses.asdict(req), "snap": {"toplevel": "/work/app", "head": head, "scope": "", "project_root": "/work/app",
                                                          "notes": [], "roots": ["/work/app"], "dep_dirs": []}}
    job_id = paths.new_job_id()
    return eng.store.create_job(JobRecord(id=job_id, idem_key=job_id, project_uid=UID, project_name="app", request_json=json.dumps(ctx),
                                          state=state, peer_install_id="iid-b", peer_label="b", snapshot_commit="a" * 40,
                                          created_at=now, updated_at=now))


def test_cancel_of_a_waiting_job_is_synchronous_and_never_calls_the_target(rig) -> None:
    rec = seed(rig, JobState.WAITING_APPROVAL)
    rig.cancel(rec.id, "denied")
    got = rig.get(rec.id)
    assert got.state == JobState.STOPPED and got.error_code == "cancelled"
    assert rig.target.calls == []


def test_stop_of_a_running_job_asks_once_then_releases(rig) -> None:
    rec = seed(rig, JobState.RUNNING)
    got = asyncio.run(rig.stop(rec.id))
    assert got.state == JobState.STOPPED
    assert [c[0] for c in rig.target.calls] == ["stop", "release"] and rig.target.calls[0][1] is False


def test_stop_that_cannot_reach_or_is_refused_leaves_the_job_lost_and_the_sweep_asks_again(rig) -> None:
    for error in (JobError("unreachable", "down", 502), JobError("pack_restricted", "no", 403)):
        rig.target.calls.clear()
        rig.target.plan = {"stop": [error]}
        rec = seed(rig, JobState.RUNNING)
        assert asyncio.run(rig.stop(rec.id)).state == JobState.LOST
        rig.target.calls.clear()
        asyncio.run(rig.sweep())
        assert ("stop", True) in rig.target.calls


def test_stop_of_a_job_the_host_forgot_ends_it(rig) -> None:
    rig.target.plan = {"stop": [JobError("unknown_job", "gone", 404)]}
    rec = seed(rig, JobState.RUNNING)
    assert asyncio.run(rig.stop(rec.id)).state == JobState.STOPPED


def test_recover_tracks_running_jobs_again_and_leaves_waiting_ones(rig) -> None:
    running, waiting = seed(rig, JobState.RUNNING), seed(rig, JobState.WAITING_APPROVAL)
    assert asyncio.run(rig.recover()) == 1
    assert rig.spawned == [running.id]
    assert rig.get(waiting.id).state == JobState.WAITING_APPROVAL


def test_sweep_fails_an_approval_older_than_a_day(rig) -> None:
    old, fresh = seed(rig, JobState.WAITING_APPROVAL, age=25 * 3600), seed(rig, JobState.WAITING_APPROVAL, age=60)
    asyncio.run(rig.sweep())
    assert rig.get(old.id).state == JobState.FAILED and rig.get(old.id).error_code == "approval_expired"
    assert rig.get(fresh.id).state == JobState.WAITING_APPROVAL


def test_silence_is_measured_on_the_clock_a_sleeping_computer_does_not_advance(tmp_path) -> None:
    target = FakeTarget()
    wall, mono = Clock(), Clock(50.0)

    async def no_sleep(_s: float) -> None:
        mono.now += 60.0
        await asyncio.sleep(0)

    state, jobs = tmp_path / "s", tmp_path / "j"
    state.mkdir()
    jobs.mkdir()
    eng = Engine(state_dir=state, jobs_root=jobs, install_id="iid-a", target_for=lambda _i: target, clock=wall, sleep=no_sleep, mono=mono,
                 open_db=lambda: None, lost_after_s=90.0)  # type: ignore[arg-type]
    eng.clock = wall  # type: ignore[attr-defined]
    rec = seed(eng, JobState.RUNNING)
    eng._last[rec.id] = mono()
    wall.now += 300.0
    target.plan = {"status": [JobError("unreachable", "link not back yet", 502), None]}
    assert asyncio.run(eng._peer(rec.id, "iid-b", lambda t: t.status(rec.id))).state == HostState.RUNNING
    target.plan = {"status": [JobError("unreachable", "down", 502)] * 5}
    with pytest.raises(engine_run.Lost):
        asyncio.run(eng._peer(rec.id, "iid-b", lambda t: t.status(rec.id)))


def test_bundle_ladder(rig, monkeypatch, tmp_path) -> None:
    made: List[List[str]] = []

    def fake_make(side: str, ref: str, not_commits: List[str], out: str) -> int:
        made.append(list(not_commits))
        Path(out).write_bytes(b"x")
        return 1

    monkeypatch.setattr(bundle_io, "make_bundle", fake_make)
    monkeypatch.setattr(bundle_io, "confirmed_tips", lambda *_a, **_k: ["tip"])
    rig.store.base_set(UID, "iid-b", "base")
    unverified = lambda: JobError("bundle_unverified", "no", 409)  # noqa: E731
    rec = seed(rig, JobState.MIRRORING)
    rig.target.plan = {"start": [unverified(), unverified(), None]}
    asyncio.run(rig._mirror_start(rec))
    assert made == [["tip", "base"], ["tip"], []]
    assert len(rig.carried) == 1 and rig.store.base_get(UID, "iid-b") is None

    made.clear()
    rig.target.plan = {"start": [unverified(), unverified(), unverified()]}
    with pytest.raises(JobError) as err:
        asyncio.run(rig._mirror_start(seed(rig, JobState.MIRRORING)))
    assert err.value.code == "bundle_unverified" and "could not read the code" in err.value.detail and len(made) == 3


def test_a_host_refusal_at_start_ends_the_job_here_not_failed(rig, monkeypatch) -> None:
    async def refuse(_rec: Any) -> None:
        raise JobError("host_busy", "is busy", 503)

    monkeypatch.setattr(rig, "_mirror_start", refuse)
    rec = seed(rig, JobState.MIRRORING)
    asyncio.run(rig._run(rec.id))
    got = rig.get(rec.id)
    assert got.state == JobState.HERE and "busy" in (got.error_detail or "")


def test_key_lock_serialises_and_cleans_up(rig) -> None:
    inside, worst = [0], [0]

    async def section() -> None:
        async with rig._key_lock("k"):
            inside[0] += 1
            worst[0] = max(worst[0], inside[0])
            await asyncio.sleep(0.01)
            inside[0] -= 1

    async def main() -> None:
        await asyncio.gather(section(), section(), section())

    asyncio.run(main())
    assert worst[0] == 1 and rig._locks == {}


def test_result_must_be_a_single_child_of_the_snapshot(tmp_path) -> None:
    import subprocess

    def g(*a: str) -> str:
        return subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@x", *a], capture_output=True, text=True, check=True).stdout.strip()

    g("init", "-q", "-b", "main")
    (tmp_path / "a").write_text("1")
    g("add", "a")
    g("commit", "-qm", "one")
    one = g("rev-parse", "HEAD")
    (tmp_path / "a").write_text("2")
    g("commit", "-qam", "two")
    two = g("rev-parse", "HEAD")
    side = str(tmp_path / ".git")
    assert engine_run.RunMixin._is_child_of(side, two, one) is True
    assert engine_run.RunMixin._is_child_of(side, one, two) is False
    with pytest.raises(JobError) as err:
        land.land(str(tmp_path), side, one, "--output=/tmp/x", "job_000000000001", snapshot_at=0.0)
    assert err.value.code == "bad_commit"


def test_land_refuses_dependency_folders_and_case_variants_of_git(tmp_path) -> None:
    root = str(tmp_path.resolve())
    for rel in ("node_modules/x.js", ".venv/lib/site.py", ".GIT/hooks/pre-commit", "a/.Git/config"):
        with pytest.raises(JobError):
            land._safe(rel, root)
    (tmp_path / ".git").mkdir()
    (tmp_path / "x").symlink_to(tmp_path / ".git")
    with pytest.raises(JobError):
        land._safe("x/hooks/pre-commit", root)


def test_a_leftover_backup_is_restored_before_a_land_and_never_snapshotted(tmp_path) -> None:
    top = str(tmp_path)
    (tmp_path / ".a.txt.carn-land-bak").write_text("mine")
    (tmp_path / ".a.txt.carn-land-tmp").write_text("half")
    land._restore_leftovers(top, ["a.txt"], {"a.txt": None}, str(tmp_path / "nowhere"))
    assert (tmp_path / "a.txt").read_text() == "mine" and not (tmp_path / ".a.txt.carn-land-tmp").exists()
    assert guards.skip_reason("sub/.a.txt.carn-land-bak", top) and guards.skip_reason("x/.y.carn-land-tmp", top)


def test_policy_refuses_what_the_wire_would_refuse_later(tmp_path) -> None:
    store = JobStore(tmp_path)
    for kw in ({"bring_back": ["/abs"]}, {"carry": ["../x"]}, {"setup": ["x"] * 11}, {"setup": ["y" * 2001]}):
        with pytest.raises(ValueError):
            policy_mod.set_lists(store, UID, **kw)
    policy_mod.set_lists(store, UID, bring_back=["out/*.txt"], setup=["npm ci"])
    assert policy_mod.get(store, UID).bring_back == ["out/*.txt"]


def test_outputs_are_prefixed_with_the_scope() -> None:
    pol = policy_mod.Policy(project_uid=UID, bring_back=["dist/*.js"])
    req = JobRequest(command="x", folder="/a/sub", outputs=["a.report"])
    assert engine_run.outputs_of(req, pol, "sub") == ["sub/a.report", "dist/*.js"]
    assert engine_run.outputs_of(req, pol) == ["a.report", "dist/*.js"]


def test_replace_roots_only_at_a_path_boundary() -> None:
    assert _replace_roots("cat /a/proj-old/x /a/proj/y '/a/proj'", ["/a/proj"], "/slot") == "cat /a/proj-old/x /slot/y '/slot'"


def test_a_cancelled_blocking_step_finishes_before_the_cancel_lands() -> None:
    done = threading.Event()

    def slow() -> int:
        time.sleep(0.3)
        done.set()
        return 1

    async def main() -> None:
        task = asyncio.ensure_future(_uninterruptible(slow))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert done.is_set()

    asyncio.run(main())


def test_host_gives_back_a_slot_no_live_job_holds(tmp_path) -> None:
    host = Host(state_dir=tmp_path, jobs_root=tmp_path / "j", install_id="iid-b", open_db=lambda: None)  # type: ignore[arg-type]
    for call in (host.recover, lambda: host.sweep(time.time())):
        assert host.store.slot_claim(UID, str(tmp_path), lambda n: str(tmp_path / f"slot{n}"), "job_0000000000aa", max_slots=3) is not None
        assert folders.busy_count(host.store, UID) == 1
        call()
        assert folders.busy_count(host.store, UID) == 0


def test_the_sweep_sees_an_old_waiting_job_behind_a_flood_of_finished_rows(rig) -> None:
    old = seed(rig, JobState.WAITING_APPROVAL, age=3 * 24 * 3600)
    for _ in range(510):
        seed(rig, JobState.HERE)
    rig._sweep_sync(rig.clock())  # type: ignore[attr-defined]
    got = rig.store.get_job(old.id)
    assert got is not None and got.state == JobState.FAILED and got.error_code == "approval_expired"


def test_the_sweep_deletes_ended_rows_after_a_week_and_keeps_recent_ones(rig) -> None:
    gone = seed(rig, JobState.DONE, age=9 * 24 * 3600)
    fresh = seed(rig, JobState.HERE)
    rig._sweep_sync(rig.clock())  # type: ignore[attr-defined]
    assert rig.store.get_job(gone.id) is None and rig.store.events(gone.id) == [] and rig.store.get_job(fresh.id) is not None


def test_the_start_carries_the_callers_air_gap_mark(rig) -> None:
    rec = seed(rig, JobState.MIRRORING)
    ctx = engine_run.load_ctx(rec)
    assert rig._start_body(rec, ctx, "blob-1").air_gap is False
    assert rig._air_gap(UID) is False
    with closing(sqlite3.connect(rig.db_file)) as conn:  # type: ignore[attr-defined]
        conn.execute("UPDATE projects SET air_gap = 1")
        conn.commit()
    assert rig._air_gap(UID) is True and rig._start_body(rec, ctx, "blob-1", True).air_gap is True


def test_two_identical_proposes_awaited_together_make_one_job(rig) -> None:
    async def slow_propose(req: JobRequest, key: str) -> JobRecord:
        await asyncio.sleep(0.02)
        return rig.store.create_job(JobRecord(id=paths.new_job_id(), idem_key=key, state=JobState.RUNNING, peer_install_id="iid-b"))

    rig._propose = slow_propose  # type: ignore[method-assign]

    async def both():
        req = JobRequest(command="pytest -q", folder="/work/app")
        return await asyncio.gather(rig.propose(req), rig.propose(JobRequest(command="pytest -q", folder="/work/app")))

    first, second = asyncio.run(both())
    assert first.id == second.id and len(rig.store.list_jobs(limit=10)) == 1

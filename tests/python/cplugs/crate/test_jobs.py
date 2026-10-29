
from __future__ import annotations

import asyncio
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.db import connect, db_path_for
from src.cplugs.crate import constants as K
from src.cplugs.crate import start
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.jobs import runner, state
from src.cplugs.crate.jobs.sweep import sweep_interrupted
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.writer import run_export
from tests.python.cplugs.crate.api_world import ApiWorld, stop_runner
from tests.python.cplugs.crate.crate_world import env_for, make_world, session_request


@pytest.fixture(autouse=True)
def free_slot():
    stop_runner()
    yield
    stop_runner()


def _blocking(gate: threading.Event, seen: List[str]) -> Any:
    def work(handle: JobHandle) -> Dict[str, Any]:
        handle.phase(K.PHASE_VERIFYING)
        while not gate.wait(0.01):
            handle.check()
        seen.append("ran")
        return {"ok": True}

    return work


def test_one_slot_and_the_topic(tmp_path: Path) -> None:
    pushed: List[tuple] = []
    gate, seen = threading.Event(), []
    job_id = runner.start(tmp_path, K.KIND_VERIFY, {"level": "quick"}, _blocking(gate, seen),
                          notify=lambda name, key: pushed.append((name, key)))
    with pytest.raises(runner.JobBusy) as busy:
        runner.start(tmp_path, K.KIND_VERIFY, {}, lambda h: {}, notify=lambda n, k: None)
    assert busy.value.code == "job_busy" and busy.value.job_id == job_id
    gate.set()
    assert runner.join(10)
    rec = state.load(state.jobs_dir(tmp_path), job_id)
    assert rec.state == K.STATE_DONE and rec.result == {"ok": True} and seen == ["ran"]
    assert pushed and all(p == ("jobs", job_id) for p in pushed)
    second = runner.start(tmp_path, K.KIND_VERIFY, {}, lambda h: {"n": 2}, notify=lambda n, k: None)
    assert runner.join(10) and state.load(state.jobs_dir(tmp_path), second).result == {"n": 2}


def test_the_topic_is_declared_and_named_through_the_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    job_id = runner.start(tmp_path / "w", K.KIND_COPY, {}, lambda h: {}, notify=api.ctx.notify)
    assert runner.join(10)
    assert f"cplug.crate.jobs:{job_id}" in api.published


def test_progress_is_coalesced_and_a_phase_change_is_forced(tmp_path: Path) -> None:
    clock = {"t": 100.0}
    pushed: List[str] = []
    saved_phases: List[str] = []

    def work(handle: JobHandle) -> Dict[str, Any]:
        handle.phase(K.PHASE_FILES, total=1000)
        for _ in range(50):
            handle.add(10)
        clock["t"] += K.PROGRESS_NOTIFY_S
        handle.add(10)
        saved_phases.append(state.load(state.jobs_dir(tmp_path), handle.job_id).phase)
        handle.phase(K.PHASE_SEALING)
        return {}

    runner.start(tmp_path, K.KIND_EXPORT, {}, work, notify=lambda n, k: pushed.append(k), clock=lambda: clock["t"])
    assert runner.join(10)
    assert len(pushed) == 5, pushed
    assert saved_phases == [K.PHASE_FILES]


def test_cancel_stops_the_job_and_on_stop_cancels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gate, seen = threading.Event(), []
    job_id = runner.start(tmp_path, K.KIND_VERIFY, {}, _blocking(gate, seen), notify=lambda n, k: None)
    assert runner.cancel(job_id) and not runner.cancel("job-19700101T000000Z-00000000")
    assert runner.join(10)
    rec = state.load(state.jobs_dir(tmp_path), job_id)
    assert rec.state == K.STATE_CANCELLED and rec.error["code"] == "cancelled" and seen == []
    (tmp_path / "api").mkdir()
    api = ApiWorld(tmp_path / "api", monkeypatch)
    other = runner.start(api.env.work, K.KIND_VERIFY, {}, _blocking(threading.Event(), seen), notify=lambda n, k: None)
    asyncio.run(start.on_stop(api.ctx))
    assert runner.running_id() is None
    assert state.load(api.jobs_root(), other).state == K.STATE_CANCELLED


def test_an_unknown_error_is_recorded_as_a_crash_and_raised(tmp_path: Path) -> None:
    caught: List[str] = []
    previous = threading.excepthook
    threading.excepthook = lambda args: caught.append(args.exc_type.__name__)
    try:
        job_id = runner.start(tmp_path, K.KIND_VERIFY, {}, lambda h: 1 / 0, notify=lambda n, k: None)
        assert runner.join(10)
    finally:
        threading.excepthook = previous
    rec = state.load(state.jobs_dir(tmp_path), job_id)
    assert rec.state == K.STATE_FAILED and rec.error == {"code": K.E_JOB_CRASHED, "detail": "ZeroDivisionError"}
    assert caught == ["ZeroDivisionError"]


def test_the_sweep_removes_only_our_temp_paths(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    env = env_for(w)
    crates = Path(w.state) / "crates"
    crates.mkdir()
    partial = crates / ".crate-x.crate.partial"
    partial.write_bytes(b"half")
    drill = env.work / K.EXTRACT_DIR / f"{K.DRILL_PREFIX}abcdef012345"
    (drill / "inner").mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    root = state.jobs_dir(env.work)
    rec = state.JobRecord(job_id=state.new_job_id(), kind=K.KIND_EXPORT, phase=K.PHASE_FILES, created_at=1.0,
                          updated_at=1.0, temp_paths=[str(partial), str(drill), str(victim)])
    state.save(root, rec)
    assert sweep_interrupted(env) == 1
    after = state.load(root, rec.job_id)
    assert after.state == K.STATE_FAILED and after.error["code"] == K.E_INTERRUPTED and after.temp_paths == []
    assert not partial.exists() and not drill.exists() and victim.read_text() == "keep me"
    assert sweep_interrupted(env) == 0


def _bundle_ids(state_dir: Path) -> List[str]:
    with closing(connect(db_path_for(state_dir))) as conn:
        return [r[0] for r in conn.execute("SELECT bundle_id FROM export_bundles")]


def _forget(state_dir: Path, bundle_id: str) -> None:
    with closing(connect(db_path_for(state_dir))) as conn:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM export_pointers WHERE bundle_id = ?", (bundle_id,))
        conn.execute("DELETE FROM export_bundles WHERE bundle_id = ?", (bundle_id,))
        conn.execute("COMMIT")


def test_a_crash_between_publish_and_record_is_recorded_by_the_sweep(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    env = env_for(w)
    handle = JobHandle("x")
    result = run_export(env, build_plan(env, session_request()), handle)
    _forget(Path(w.state), result.bundle_id)
    assert result.bundle_id not in _bundle_ids(Path(w.state))
    root = state.jobs_dir(env.work)
    rec = state.JobRecord(job_id=state.new_job_id(), kind=K.KIND_EXPORT, phase=K.PHASE_RECORDING, created_at=time.time(),
                          updated_at=time.time(), publish=handle.publish)
    state.save(root, rec)
    assert sweep_interrupted(env) == 1
    after = state.load(root, rec.job_id)
    assert after.state == K.STATE_DONE and after.result["recovered"] is True and after.result["recorded"] is True
    assert _bundle_ids(Path(w.state)).count(result.bundle_id) == 1
    result.path.write_bytes(b"not the crate")
    _forget(Path(w.state), result.bundle_id)
    rec2 = state.JobRecord(job_id=state.new_job_id(), kind=K.KIND_EXPORT, phase=K.PHASE_PUBLISHING,
                           created_at=time.time(), updated_at=time.time(), publish=handle.publish)
    state.save(root, rec2)
    assert sweep_interrupted(env) == 1
    assert state.load(root, rec2.job_id).error["code"] == K.E_INTERRUPTED_UNVERIFIED
    assert result.bundle_id not in _bundle_ids(Path(w.state)) and result.path.exists()


def test_prune_keeps_running_and_recent_records(tmp_path: Path) -> None:
    root = state.jobs_dir(tmp_path)
    old = 1000.0
    for job_state in (K.STATE_DONE, K.STATE_RUNNING):
        state.save(root, state.JobRecord(job_id=state.new_job_id(old), kind=K.KIND_COPY, state=job_state,
                                         created_at=old, updated_at=old))
    fresh = state.JobRecord(job_id=state.new_job_id(), kind=K.KIND_COPY, state=K.STATE_DONE, created_at=time.time(),
                            updated_at=time.time())
    state.save(root, fresh)
    assert state.prune(root) == 1
    assert sorted(r.state for r in state.all_jobs(root)) == [K.STATE_DONE, K.STATE_RUNNING]


@pytest.mark.parametrize("ending", ["done", "failed", "cancelled"])
def test_a_failed_final_save_still_frees_the_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: str) -> None:
    real_save = state.save

    def full_disk(root: Path, rec: state.JobRecord) -> None:
        if rec.state != K.STATE_RUNNING:
            raise OSError(28, "No space left on device")
        real_save(root, rec)

    def work(handle: JobHandle) -> Dict[str, Any]:
        if ending == "failed":
            raise runner.JobFailed("verify_failed", ["blob_corrupt"])
        if ending == "cancelled":
            handle.cancel()
            handle.check()
        return {"ok": True}

    monkeypatch.setattr(state, "save", full_disk)
    runner.start(tmp_path, K.KIND_VERIFY, {}, work, notify=lambda n, k: None)
    assert runner.join(5.0) and runner.running_id() is None
    monkeypatch.setattr(state, "save", real_save)
    next_id = runner.start(tmp_path, K.KIND_VERIFY, {}, lambda h: {"ok": True}, notify=lambda n, k: None)
    assert runner.join(5.0) and state.load(state.jobs_dir(tmp_path), next_id).state == K.STATE_DONE

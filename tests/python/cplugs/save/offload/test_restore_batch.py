
from __future__ import annotations

import asyncio
import subprocess
import threading
from pathlib import Path
from typing import Any, List

import pytest
from fastapi import HTTPException

from src.core.backup_health import constants as HK
from src.core.backup_health import vault_check
from src.plugins.save import routes as save_routes
from src.plugins.save.offload import alerts, batch, batch_routes, offload_routes, restore_batch, restore_batch_routes
from src.plugins.save.offload import constants as C
from src.plugins.save.vault import health
from src.plugins.sdk.blob_codec import Throttle
from tests.python.cplugs.save.offload.fleet import build_fleet, conv_id, ledger_of
from tests.python.cplugs.save.offload.test_restore_chain import OFFLOAD_DIR, forbidden_imports
from tests.python.cplugs.save.vault_helpers import World


@pytest.fixture(autouse=True)
def fresh_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(restore_batch_routes, "RUNNER", restore_batch.RestoreBatchRunner())
    monkeypatch.setattr(batch_routes, "RUNNER", batch.BatchRunner())
    monkeypatch.setattr(batch_routes, "make_pace", lambda: Throttle(sleep=lambda seconds: None))
    monkeypatch.setattr(C, "RESTORE_BUSY_WAIT_SECONDS", 0.0)


def endpoint(path: str, method: str) -> Any:
    return next(r.endpoint for r in save_routes.router.routes if getattr(r, "path", "").endswith(path) and method in getattr(r, "methods", ()))


def start(sessions: List[str], conversations: List[str] = ()) -> Any:
    out = asyncio.run(endpoint("/offload/restore-batch", "POST")(restore_batch_routes.RestoreBatchBody(session_uuids=list(sessions), conversation_ids=list(conversations))))
    assert restore_batch_routes.RUNNER.join(timeout=60)
    return out


def finished(batch_id: str) -> Any:
    return asyncio.run(endpoint("/offload/restore-batch/{batch_id}", "GET")(batch_id))


def offload(world: World, count: int) -> None:
    for i in range(1, count + 1):
        offload_routes._run_if_enabled(f"S{i}", False)
        assert not world.transcript(conv_id(i)).exists()


def test_a_restore_batch_puts_every_chosen_session_back_in_one_run_and_starts_no_session(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 6)
    offload(world, 4)
    assert set(ledger_of(world).read()) == {conv_id(i) for i in range(1, 5)}

    def no_process(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a restore batch must not start a process")

    monkeypatch.setattr(subprocess, "Popen", no_process)
    monkeypatch.setattr(subprocess, "run", no_process)
    out = start(["S1", "S2", "S3"], [conv_id(4)])
    assert out.state == C.BATCH_RUNNING and out.planned == 4
    done = finished(out.id)
    assert done.state == C.BATCH_DONE and (done.restored, done.failed) == (4, 0)
    assert all(world.transcript(conv_id(i)).exists() for i in range(1, 5))
    assert ledger_of(world).read() == {}, "a restored conversation's ledger entry is cleared"
    assert not health.read(world.state).get("offload_alerts", {}).get("restore"), "a clean batch raises no alert"


def test_a_failed_target_is_recorded_the_rest_go_on_and_one_sticky_alert_is_raised_then_cleared(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 6)
    offload(world, 3)
    done = finished(start(["S1", "S99", "S2"]).id)
    assert done.state == C.BATCH_DONE and (done.restored, done.failed) == (2, 1)
    assert [(i.id, i.status, i.code) for i in done.items] == [("S1", "restored", ""), ("S99", "failed", C.CODE_UNKNOWN_SESSION), ("S2", "restored", "")]
    assert alerts.current(world.state, alerts.RESTORE)["conversations"] == ["S99"]
    firing = {v.key: v for v in vault_check.check_vault(world.state, 2_000_000_000.0) if v.state == "firing"}
    verdict = firing[HK.KEY_VAULT_RESTORE_FAILED]
    assert verdict.sticky and verdict.severity == "error" and verdict.params["targets"] == "S99" and verdict.params["count"] == 1
    clean = finished(start(["S3"]).id)
    assert (clean.restored, clean.failed) == (1, 0)
    assert alerts.current(world.state, alerts.RESTORE)["conversations"] == ["S99"], "a clean batch of other targets must not clear a failure that still stands"


def test_restoring_a_target_that_failed_before_takes_it_out_of_the_alert_and_the_rest_stay(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 4)
    offload(world, 2)
    alerts.record(world.state, alerts.RESTORE, blobs=(), conversations=["S2", "S99"], now=1.0)
    start(["S2"])
    assert alerts.current(world.state, alerts.RESTORE)["conversations"] == ["S99"]
    alerts.record(world.state, alerts.RESTORE, blobs=(), conversations=["S1"], now=2.0)
    start(["S1"])
    assert alerts.current(world.state, alerts.RESTORE)["conversations"] == []


def test_a_crash_ends_the_batch_stopped_and_never_names_an_empty_id_in_the_alert(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 3)
    offload(world, 2)
    calls: List[str] = []
    real = restore_batch_routes.restore_one

    def crashing(target: restore_batch.Target) -> restore_batch.RestoreStep:
        calls.append(target.id)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return real(target)

    monkeypatch.setattr(restore_batch_routes, "restore_one", crashing)
    done = finished(start(["S1", "S2", "S1x"]).id)
    assert done.state == C.BATCH_STOPPED and calls == ["S1", "S2"]
    assert [(i.id, i.code) for i in done.items] == [("S1", ""), ("", "batch_crashed")]
    assert "" not in alerts.current(world.state, alerts.RESTORE).get("conversations", [])


def test_a_vault_that_goes_offline_stops_the_batch_at_the_first_refusal(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 4)
    offload(world, 3)
    tried: List[str] = []

    def offline(target: restore_batch.Target) -> Any:
        tried.append(target.id)
        raise HTTPException(status_code=409, detail={"code": "vault_unavailable", "detail": "the vault is not reachable"})

    monkeypatch.setattr(restore_batch_routes, "_restore_once", offline)
    done = finished(start(["S1", "S2", "S3"]).id)
    assert tried == ["S1"] and done.state == C.BATCH_STOPPED and (done.restored, done.failed) == (0, 1)
    assert done.items[0].code == "vault_unavailable"


def test_a_collision_fails_that_target_and_writes_nothing_of_it(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 3)
    offload(world, 2)
    world.transcript(conv_id(1)).write_text("something else\n")
    done = finished(start(["S1", "S2"]).id)
    assert (done.restored, done.failed) == (1, 1) and done.items[0].code == "conflict"
    assert world.transcript(conv_id(1)).read_text() == "something else\n" and world.transcript(conv_id(2)).exists()


def test_a_stop_ends_the_batch_after_the_target_in_flight() -> None:
    runner = restore_batch.RestoreBatchRunner()
    entered, release, seen = threading.Event(), threading.Event(), []

    def slow(target: restore_batch.Target) -> restore_batch.RestoreStep:
        seen.append(target.id)
        entered.set()
        assert release.wait(10)
        return restore_batch.RestoreStep(True, conversations=1, bytes=5)

    targets = [restore_batch.Target("session", f"S{i}") for i in (1, 2, 3)]
    ended: List[restore_batch.RestoreBatch] = []
    started = runner.start(targets, slow, pace=Throttle(sleep=lambda seconds: None), on_end=ended.append)
    assert entered.wait(10)
    assert runner.stop(started.id).state == C.BATCH_RUNNING
    release.set()
    assert runner.join(10)
    final = runner.get(started.id)
    assert final.state == C.BATCH_STOPPED and seen == ["S1"] and [i.id for i in final.items] == ["S1"] and ended[0].state == C.BATCH_STOPPED


def test_a_start_names_valid_targets_and_one_batch_runs_at_a_time(tmp_path, monkeypatch) -> None:
    for sessions, conversations in (([], []), ([""], []), ([], ["../etc"]), ([f"S{i}" for i in range(C.RESTORE_BATCH_MAX + 1)], [])):
        with pytest.raises(HTTPException) as caught:
            restore_batch_routes.plan_targets(sessions, conversations)
        assert caught.value.status_code == 400 and caught.value.detail["code"] == C.CODE_BAD_TARGETS
    assert restore_batch_routes.plan_targets(["S1", "S1"], ["a" * 36]) == [restore_batch.Target("session", "S1"), restore_batch.Target("conversation", "a" * 36)]
    release = threading.Event()
    restore_batch_routes.RUNNER.start([restore_batch.Target("session", "S1")], lambda t: (release.wait(10), restore_batch.RestoreStep(True))[1], pace=Throttle(sleep=lambda s: None))
    with pytest.raises(HTTPException) as busy:
        restore_batch_routes.start_batch(["S2"], [])
    assert busy.value.status_code == 409 and busy.value.detail["code"] == C.CODE_BATCH_BUSY
    release.set()
    assert restore_batch_routes.RUNNER.join(10)


def test_the_new_modules_and_routes_cannot_reach_a_session() -> None:
    for name in ("restore_batch.py", "restore_batch_routes.py"):
        assert forbidden_imports((OFFLOAD_DIR / name).read_text()) == [], name
    routes = [r for r in save_routes.router.routes if "restore-batch" in getattr(r, "path", "")]
    assert len(routes) == 3
    import inspect
    for route in routes:
        assert set(inspect.signature(route.endpoint).parameters) <= {"batch_id", "body"}

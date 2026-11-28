
from __future__ import annotations

import asyncio
import threading
from typing import Any, List

import pytest
from fastapi import HTTPException

from src.plugins.save import routes as save_routes
from src.plugins.save.offload import batch, batch_routes, ledger as ledger_mod
from src.plugins.save.offload import constants as C
from src.plugins.save.vault import constants as K
from src.plugins.save.vault import retention
from src.plugins.sdk.blob_codec import Throttle
from tests.python.cplugs.save.offload.fleet import build_fleet, conv_id, delete_a_chunk, ledger_of, store_settings
from tests.python.cplugs.save.vault_helpers import World


@pytest.fixture(autouse=True)
def fresh_runner(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    rests: List[float] = []
    monkeypatch.setattr(batch_routes, "RUNNER", batch.BatchRunner())
    monkeypatch.setattr(batch_routes, "make_pace", lambda: Throttle(sleep=rests.append))
    return rests


def endpoint(path: str, method: str) -> Any:
    return next(r.endpoint for r in save_routes.router.routes if getattr(r, "path", "").endswith(path) and method in getattr(r, "methods", ()))


def start(max_sessions: int = 50, idle_days: int = 30) -> Any:
    out = asyncio.run(endpoint("/offload/batch", "POST")(batch_routes.BatchBody(max_sessions=max_sessions, idle_days=idle_days)))
    assert batch_routes.RUNNER.join(timeout=60)
    return out


def finished(batch_id: str) -> Any:
    return asyncio.run(endpoint("/offload/batch/{batch_id}", "GET")(batch_id))


def assess_twice(world: World, before: Any = None) -> Any:
    return retention.assess(world.vault, now=2_000_000_000.0)


def test_a_batch_is_refused_while_the_switch_is_off_and_nothing_moves(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 3)
    store_settings(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(endpoint("/offload/batch", "POST")(batch_routes.BatchBody(max_sessions=10, idle_days=30)))
    assert caught.value.status_code == 409 and caught.value.detail["code"] == C.CODE_OFFLOAD_DISABLED
    assert batch_routes.RUNNER.latest() is None and not ledger_of(world).path.exists()
    assert world.transcript(conv_id(1)).exists()


def test_a_batch_offloads_each_session_skips_the_unverified_one_and_raises_no_mass_gone(tmp_path, monkeypatch, fresh_runner) -> None:
    world = build_fleet(tmp_path, monkeypatch, 12)
    assess_twice(world)
    bad = delete_a_chunk(world, conv_id(5))
    out = start()
    assert out.state == C.BATCH_RUNNING
    done = finished(out.id)
    assert done.state == C.BATCH_DONE and (done.offloaded, done.skipped, done.failed) == (11, 1, 0)
    skipped = [i for i in done.items if i.status == C.ITEM_SKIPPED]
    assert [(i.session_uuid, i.code) for i in skipped] == [("S5", C.CODE_VERIFY_FAILED)]
    assert set(ledger_of(world).read()) == {conv_id(i) for i in range(1, 13) if i != 5}
    assert world.transcript(conv_id(5)).exists() and not world.transcript(conv_id(1)).exists()
    assert len(fresh_runner) == 12, "the engine throttle rests after every session it works on"
    state = assess_twice(world)
    assert state["mass_gone"] is None, f"planned removals must not alarm (bad chunk {bad[:8]})"


def test_the_same_removals_without_the_ledger_would_alarm(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 12)
    assess_twice(world)
    start()
    ledger_of(world).path.unlink()
    assert assess_twice(world)["mass_gone"] is not None


def test_a_real_loss_during_a_batch_still_alarms(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(K, "MASS_GONE_THRESHOLD", 3)
    world = build_fleet(tmp_path, monkeypatch, 12)
    assess_twice(world)
    start(max_sessions=6)
    out_now = set(ledger_of(world).read())
    assert len(out_now) == 6
    for i in [n for n in range(1, 13) if conv_id(n) not in out_now][:3]:
        world.transcript(conv_id(i)).unlink()
    report = assess_twice(world)["mass_gone"]
    assert report is not None and report["count"] == 3


def test_stop_ends_the_batch_after_the_session_in_flight(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 5)
    real = batch_routes.offload_routes._run_if_enabled

    def stopping(session_uuid: str, dry_run: bool) -> Any:
        out = real(session_uuid, dry_run)
        asyncio.run(endpoint("/offload/batch/{batch_id}/stop", "POST")(batch_routes.RUNNER.latest().id))
        return out

    monkeypatch.setattr(batch_routes.offload_routes, "_run_if_enabled", stopping)
    out = start()
    after = finished(out.id)
    assert after.state == C.BATCH_STOPPED and after.offloaded == 1 and len(after.items) == 1
    assert set(ledger_of(world).read()) == {conv_id(1)} and world.transcript(conv_id(2)).exists()


def test_a_failure_stops_the_batch_at_the_first_failed_session(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 5)
    real = batch_routes.offload_routes._run_if_enabled

    def breaking(session_uuid: str, dry_run: bool) -> Any:
        if session_uuid == "S2":
            raise HTTPException(status_code=409, detail={"code": C.CODE_MOVE_FAILED, "detail": "disk full", "reasons": [], "stuck": []})
        return real(session_uuid, dry_run)

    monkeypatch.setattr(batch_routes.offload_routes, "_run_if_enabled", breaking)
    after = finished(start().id)
    assert after.state == C.BATCH_FAILED and (after.offloaded, after.failed) == (1, 1) and len(after.items) == 2
    assert after.items[-1].code == C.CODE_MOVE_FAILED and world.transcript(conv_id(3)).exists()


def test_switching_the_offload_off_mid_batch_stops_the_next_removal(tmp_path, monkeypatch, fresh_runner) -> None:
    world = build_fleet(tmp_path, monkeypatch, 4)
    live = store_settings(monkeypatch, offloadEnabled=True)
    monkeypatch.setattr(batch_routes, "make_pace", lambda: Throttle(sleep=lambda s: live.update(offloadEnabled=False)))
    after = finished(start().id)
    assert after.state == C.BATCH_FAILED and after.offloaded == 1 and after.items[-1].code == C.CODE_OFFLOAD_DISABLED
    assert world.transcript(conv_id(2)).exists()


def test_only_one_batch_runs_at_a_time_and_an_unknown_id_is_404(tmp_path, monkeypatch) -> None:
    build_fleet(tmp_path, monkeypatch, 3)
    gate = threading.Event()
    real = batch_routes.offload_routes._run_if_enabled
    monkeypatch.setattr(batch_routes.offload_routes, "_run_if_enabled", lambda s, d: (gate.wait(30), real(s, d))[1])
    first = asyncio.run(endpoint("/offload/batch", "POST")(batch_routes.BatchBody(max_sessions=3, idle_days=30)))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(endpoint("/offload/batch", "POST")(batch_routes.BatchBody(max_sessions=3, idle_days=30)))
    assert caught.value.status_code == 409 and caught.value.detail["code"] == C.CODE_BATCH_BUSY
    gate.set()
    assert batch_routes.RUNNER.join(timeout=60) and finished(first.id).state == C.BATCH_DONE
    for call in (lambda: finished("nope"), lambda: asyncio.run(endpoint("/offload/batch/{batch_id}/stop", "POST")("nope"))):
        with pytest.raises(HTTPException) as missing:
            call()
        assert missing.value.status_code == 404


def test_the_batch_plans_only_sessions_idle_long_enough(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 3)
    out = start(idle_days=90)
    done = finished(out.id)
    assert done.state == C.BATCH_DONE and done.planned == 0 and not ledger_of(world).path.exists()


def test_a_batch_is_visible_in_the_list_answer(tmp_path, monkeypatch) -> None:
    from src.plugins.save.offload import list_routes
    build_fleet(tmp_path, monkeypatch, 2)
    out = start()
    page = list_routes.list_page(None, None, C.PAGE_DEFAULT)
    assert page.batch is not None and page.batch.id == out.id and page.batch.offloaded == 2


def test_the_batch_tools_start_only_behind_the_owners_card_and_the_switch_and_status_reads(tmp_path, monkeypatch) -> None:
    from src.plugins.save import offload_mcp
    from src.plugins.sdk import ToolError

    build_fleet(tmp_path, monkeypatch, 3)
    start_tool, status_tool = offload_mcp.TOOLS["save_offload_batch_start"], offload_mcp.TOOLS["save_offload_batch_status"]
    assert start_tool.gate == "inbox" and start_tool.prepare is not None and status_tool.gate == "read"
    args, sentence = asyncio.run(start_tool.prepare(None, None, {"max_sessions": 10}))
    assert args == {"max_sessions": 10, "idle_days": 30} and "up to 10" in sentence and "idle 30 days" in sentence
    for bad in ({"max_sessions": "10"}, {"max_sessions": 2.5}, {"max_sessions": True}, {"max_sessions": 0}, {"idle_days": -1}):
        with pytest.raises(ToolError):
            asyncio.run(start_tool.prepare(None, None, bad))
    store_settings(monkeypatch)
    with pytest.raises(ToolError, match=C.CODE_OFFLOAD_DISABLED):
        asyncio.run(offload_mcp.save_offload_batch_start(None, None, {"max_sessions": 10}))
    store_settings(monkeypatch, offloadEnabled=True)
    started = asyncio.run(offload_mcp.save_offload_batch_start(None, None, {"max_sessions": 10}))
    assert batch_routes.RUNNER.join(timeout=60)
    batch_id = batch_routes.RUNNER.latest().id
    status = asyncio.run(offload_mcp.save_offload_batch_status(None, None, {"batch_id": batch_id}))
    assert started and status and str(batch_routes.RUNNER.latest().count(C.ITEM_OFFLOADED)) == "3"
    with pytest.raises(ToolError, match="404"):
        asyncio.run(offload_mcp.save_offload_batch_status(None, None, {"batch_id": "nope"}))


def test_the_plugin_stop_ends_a_running_batch_after_the_session_in_flight() -> None:
    gate, seen = threading.Event(), []

    def slow_step(session_uuid: str) -> batch.StepResult:
        seen.append(session_uuid)
        gate.wait(10)
        return batch.StepResult(True, conversations=1, bytes=1)

    runner = batch.BatchRunner()
    runner.start(["S1", "S2", "S3"], slow_step, max_sessions=3, idle_days=30, pace=Throttle(sleep=lambda s: None))
    while not seen:
        threading.Event().wait(0.01)
    assert runner.stop_running()
    gate.set()
    assert runner.join(timeout=10)
    assert seen == ["S1"] and runner.latest().state == C.BATCH_STOPPED and not runner.stop_running()


from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

import src.config  # noqa: F401
from src.core.automations import lifecycle, targets
from src.core.byoai.native import claude_cli
from src.core.swarm.cards import capacity
from src.core.provider_ledger import refresh_guard
from src.core.automations import models as m
from src.core.automations.schedule import compile_cron, next_epoch
from src.core.automations.scheduler import Scheduler
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for
from src.core.resource_push import topics

BASE = datetime(2027, 1, 5, 12, 0, tzinfo=timezone.utc).timestamp()
RECIPE = {"kind": "recipe", "recipe": "scrooge"}
CARD = {"kind": "swarm_card", "project_id": 1, "title": "t", "summary": "s"}


class Clock:

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def env(tmp_path, monkeypatch):
    calls: List[str] = []

    async def runner(ctx, automation, run):
        calls.append(run["run_id"])
        return m.RunOutcome(status=m.SUCCEEDED, report={"ok": True})

    for kind in m.TARGET_KINDS:
        monkeypatch.setitem(targets.RUNNERS, kind, runner)
    clock, announced = Clock(BASE), []
    store = AutomationStore(storage_for(tmp_path), clock=clock, notify=announced.append)
    return SimpleNamespace(store=store, clock=clock, announced=announced, calls=calls)


def _statuses(store: AutomationStore) -> List[tuple]:
    return [(r["status"], r["reason"], r["skip_count"]) for r in reversed(store.runs(limit=200))]


def test_two_concurrent_claims_make_one_run(env):
    due = env.store.create(name="due", cron="*/15 * * * *", target=RECIPE)
    future = env.store.create(name="future", cron="0 3 1 1 *", target=RECIPE)
    env.clock.now = due["next_fire_at"] + 5
    assert due["next_fire_at"] <= env.clock.now < future["next_fire_at"]
    assert due["enabled"] and future["enabled"]
    results: List[List[Dict[str, Any]]] = []
    errors: List[BaseException] = []
    barrier = threading.Barrier(2)

    def go() -> None:
        barrier.wait()
        try:
            results.append(env.store.claim_due(env.clock.now, "boot-1"))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [] and len(results) == 2
    assert sum(len(r) for r in results) == 1
    runs = env.store.runs()
    assert [(r["automation_id"], r["status"]) for r in runs] == [(due["automation_id"], "claimed")]
    assert env.store.get(due["automation_id"])["next_fire_at"] > env.clock.now
    assert topics.AUTOMATION_RUNS in env.announced and topics.AUTOMATIONS in env.announced


def test_missed_slots_skip_and_coalesce(env):
    auto = env.store.create(name="m", cron="*/15 * * * *", target=RECIPE, misfire="skip")
    for expected in (1, 2, 3):
        slot = env.store.get(auto["automation_id"])["next_fire_at"]
        env.clock.now = slot + 600
        assert env.store.claim_due(env.clock.now, "boot-1") == []
        runs = env.store.runs()
        assert len(runs) == 1
        assert (runs[0]["status"], runs[0]["reason"], runs[0]["skip_count"]) == ("skipped", "missed_slot", expected)
    assert runs[0]["first_slot_at"] < runs[0]["last_slot_at"]
    env.clock.now = env.store.get(auto["automation_id"])["next_fire_at"] + 30
    assert len(env.store.claim_due(env.clock.now, "boot-1")) == 1


def test_disabled_automation_is_never_claimed(env):
    on = env.store.create(name="on", cron="*/15 * * * *", target=RECIPE)
    off = env.store.create(name="off", cron="*/15 * * * *", target=RECIPE, enabled=False)
    assert off["next_fire_at"] is None and on["next_fire_at"] is not None
    env.clock.now = on["next_fire_at"] + 1
    assert [r["automation_id"] for r in env.store.claim_due(env.clock.now, "b")] == [on["automation_id"]]
    assert env.store.set_enabled(on["automation_id"], False)["next_fire_at"] is None


def test_foreign_boot_run_becomes_interrupted_and_orphan_group_stops(env):
    auto = env.store.create(name="r", cron="*/15 * * * *", target=RECIPE)
    old = env.store.insert_run(auto["automation_id"], "old-boot")
    env.store.update_run(old["run_id"], status="running")
    env.store.update_run(old["run_id"], status="failed", reason="x", ended_at=1.0)
    auto2 = env.store.create(name="r2", cron="*/15 * * * *", target=RECIPE)
    stale = env.store.insert_run(auto2["automation_id"], "old-boot")
    child = subprocess.Popen(["sleep", "60"], start_new_session=True)
    other = subprocess.Popen(["sleep", "60"], start_new_session=True)
    try:
        lstart = lifecycle._lstart(child.pid)
        assert lstart
        env.store.update_run(stale["run_id"], status="running",
                             child={"pid": child.pid, "pgid": os.getpgid(child.pid), "started_lstart": lstart})
        auto3 = env.store.create(name="r3", cron="*/15 * * * *", target=RECIPE)
        keep = env.store.insert_run(auto3["automation_id"], "old-boot")
        env.store.update_run(keep["run_id"], status="running")
        auto4 = env.store.create(name="r4", cron="*/15 * * * *", target=RECIPE)
        mismatched = env.store.insert_run(auto4["automation_id"], "old-boot")
        env.store.update_run(mismatched["run_id"], status="running",
                             child={"pid": other.pid, "pgid": os.getpgid(other.pid), "started_lstart": "Mon Jan  1 00:00:00 1990"})
        failed = lifecycle.reconcile_boot(env.store, "new-boot")
        assert {r["run_id"] for r in failed} == {stale["run_id"], keep["run_id"], mismatched["run_id"]}
        assert env.store.run(stale["run_id"])["status"] == "failed"
        assert env.store.run(stale["run_id"])["reason"] == "interrupted"
        assert child.wait(timeout=10) is not None
        assert other.poll() is None
    finally:
        for proc in (child, other):
            if proc.poll() is None:
                proc.kill()
            proc.wait()
    assert lifecycle.reconcile_boot(env.store, "new-boot") == []


def test_interval_floor_and_cron_errors(env):
    now = BASE
    with pytest.raises(m.AutomationInvalid) as under:
        compile_cron("*/5 * * * *", now)
    assert under.value.code == "interval_under_15_min"
    assert compile_cron("*/15 * * * *", now) is not None
    assert compile_cron("0 7 * * mon", now) is not None
    with pytest.raises(m.AutomationInvalid) as never:
        compile_cron("0 0 30 2 *", now)
    assert never.value.code == "never_fires"
    with pytest.raises(m.AutomationInvalid) as bad:
        env.store.create(name="x", cron="*/5 * * * *", target=RECIPE)
    assert bad.value.code == "interval_under_15_min" and env.store.list_all() == []


def test_unregistered_target_kind_is_refused(env, monkeypatch):
    monkeypatch.delitem(targets.RUNNERS, "agent")
    with pytest.raises(m.AutomationInvalid) as refused:
        env.store.create(name="a", cron="*/15 * * * *", target={"kind": "agent", "folder": "/tmp/x", "prompt": "hi"})
    assert refused.value.code == "target_not_available"


def _patch_gates(monkeypatch, *, pct=10.0, floor=False, busy=None, unusable=False):
    monkeypatch.setattr(capacity, "account_for", lambda profile: "acct")
    monkeypatch.setattr(capacity, "usage_state", lambda account: capacity.Usage(pct, floor, "acct", "7d"))
    monkeypatch.setattr(refresh_guard, "busy_reason", lambda profile: busy)
    monkeypatch.setattr(claude_cli, "_login_unusable", lambda profile, account: unusable)


def _tick(env, automation_id: str) -> Dict[str, Any]:
    scheduler = Scheduler(SimpleNamespace(), env.store, clock=env.clock, boot_id="boot-1")

    async def go() -> None:
        env.clock.now = env.store.get(automation_id)["next_fire_at"] + 1
        assert await scheduler.pass_once() == 1
        if scheduler._tasks:
            await asyncio.gather(*list(scheduler._tasks))

    asyncio.run(go())
    return env.store.runs(automation_id, limit=1)[0]


def test_usage_and_refresh_gates_skip_with_named_reasons(env, monkeypatch):
    auto = env.store.create(name="g", cron="*/15 * * * *", target=RECIPE)
    aid = auto["automation_id"]
    _patch_gates(monkeypatch, pct=95.0, floor=True)
    first = _tick(env, aid)
    assert (first["status"], first["reason"]) == ("skipped", "usage_over_90") and env.calls == []
    _tick(env, aid)
    assert env.store.runs(aid, limit=1)[0]["skip_count"] == 2
    _patch_gates(monkeypatch, busy=refresh_guard.BUSY_REFRESH_LOCK)
    third = _tick(env, aid)
    assert (third["status"], third["reason"]) == ("skipped", "refresh_in_flight") and env.calls == []
    _patch_gates(monkeypatch, unusable=True)
    assert _tick(env, aid)["reason"] == "login_needs_attention"
    _patch_gates(monkeypatch, busy=refresh_guard.BUSY_CLAUDE_RUNNING)
    ran = _tick(env, aid)
    assert ran["status"] == "succeeded" and ran["notes"]["claude_running"] is True and len(env.calls) == 1
    monkeypatch.setattr(capacity, "usage_state", lambda account: capacity.Usage(None, False, None, None))
    monkeypatch.setattr(refresh_guard, "busy_reason", lambda profile: None)
    unknown = _tick(env, aid)
    assert unknown["status"] == "succeeded" and unknown["notes"]["usage"] == "unknown" and len(env.calls) == 2


def test_card_target_skips_spend_gates_and_concurrency_caps(env, monkeypatch):
    _patch_gates(monkeypatch, pct=99.0, floor=True)
    card = env.store.create(name="c", cron="*/15 * * * *", target=CARD)
    assert _tick(env, card["automation_id"])["status"] == "succeeded"
    busy = [env.store.create(name=f"b{i}", cron="0 3 1 1 *", target=CARD) for i in range(2)]
    for item in busy:
        run = env.store.insert_run(item["automation_id"], "boot-1")
        env.store.update_run(run["run_id"], status="running")
    assert len(env.store.live_runs()) == 2
    assert _tick(env, card["automation_id"])["reason"] == "two_runs_running"
    own = env.store.insert_run(card["automation_id"], "boot-1")
    env.store.update_run(own["run_id"], status="running")
    assert _tick(env, card["automation_id"])["reason"] == "previous_run_still_running"


def test_dst_observed_behavior(env):
    saved = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    try:
        schedule = compile_cron("30 2 * * *", BASE)
        eve = datetime(2026, 3, 8, 5, 0, tzinfo=timezone.utc).timestamp()
        gap = datetime.fromtimestamp(next_epoch(schedule, eve), tz=timezone.utc).astimezone()
        assert (gap.day, gap.hour, gap.minute) == (8, 3, 30)
        after = next_epoch(schedule, gap.timestamp())
        assert datetime.fromtimestamp(after, tz=timezone.utc).astimezone().day == 9
        repeat = compile_cron("30 1 * * *", BASE)
        first = next_epoch(repeat, datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc).timestamp())
        second = next_epoch(repeat, first)
        assert datetime.fromtimestamp(second, tz=timezone.utc).astimezone().day == 2
    finally:
        if saved is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved
        time.tzset()


def test_run_now_passes_the_enabled_gate_but_a_scheduled_slot_does_not(env, monkeypatch):
    _patch_gates(monkeypatch)
    auto = env.store.create(name="off", cron="*/15 * * * *", target=RECIPE)
    scheduler = Scheduler(SimpleNamespace(), env.store, clock=env.clock, boot_id="boot-1")

    async def go():
        env.clock.now = env.store.get(auto["automation_id"])["next_fire_at"] + 1
        (slot_run,) = env.store.claim_due(env.clock.now, "boot-1")
        env.store.update(auto["automation_id"], None, enabled=False)
        slot_id = await scheduler._dispatch(slot_run)
        now_run = await scheduler.run_now(auto["automation_id"])
        if scheduler._tasks:
            await asyncio.gather(*list(scheduler._tasks))
        return slot_id, now_run

    slot_id, now_run = asyncio.run(go())
    slot = env.store.run(slot_id)
    assert (slot["status"], slot["reason"], slot["trigger"]) == (m.SKIPPED, m.R_DISABLED, "schedule")
    assert len(env.calls) == 1
    done = env.store.run(now_run["run_id"])
    assert (done["trigger"], done["status"]) == ("run_now", m.SUCCEEDED)

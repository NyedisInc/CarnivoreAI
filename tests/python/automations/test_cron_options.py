
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import src.config  # noqa: F401
from src.core.automations import gates, scheduler as scheduler_module, targets
from src.core.automations import models as m
from src.core.automations.scheduler import Scheduler
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for

BASE = datetime(2027, 1, 5, 12, 0, tzinfo=timezone.utc).timestamp()
ACTION = {"kind": "recipe", "recipe": "sleep_idle_sessions"}


class Clock:

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def env(tmp_path, monkeypatch):
    w = SimpleNamespace(outcome=m.RunOutcome(status=m.FAILED, reason="boom"), delay=0.0, told=[])

    async def runner(ctx, automation, run):
        await asyncio.sleep(w.delay)
        return w.outcome

    monkeypatch.setitem(targets.RUNNERS, "recipe", runner)
    monkeypatch.setattr(gates, "evaluate", lambda *a: (None, {}))
    monkeypatch.setattr(scheduler_module, "tell_failure", lambda automation, run_id, store=None: w.told.append(run_id) or True)
    w.clock = Clock(BASE)
    w.store = AutomationStore(storage_for(tmp_path), clock=w.clock, notify=lambda _t: None)
    return w


def test_run_once_catches_up_one_run_for_many_missed_slots(env):
    auto = env.store.create(name="c", cron="*/15 * * * *", target=ACTION)
    assert auto["misfire"] == "run_once"
    env.clock.now = auto["next_fire_at"] + 5 * 3600
    claimed = env.store.claim_due(env.clock.now, "boot")
    assert [(r["trigger"], r["attempt"]) for r in claimed] == [("catch_up", 1)]
    assert env.store.get(auto["automation_id"])["next_fire_at"] > env.clock.now
    assert env.store.claim_due(env.clock.now, "boot") == []


def test_a_failed_run_is_retried_after_its_backoff_then_stops(env):
    auto = env.store.create(name="r", cron="0 3 * * *", target=ACTION, retry_max=2, retry_backoff_s=60)
    aid, attempts = auto["automation_id"], []
    for _ in range(3):
        due = env.store.settle_retry(aid, True, env.clock.now)
        if due is None:
            break
        assert env.store.next_due() == due
        env.clock.now = due - 1
        assert env.store.claim_due(env.clock.now, "boot") == []
        env.clock.now = due + 1
        (run,) = env.store.claim_due(env.clock.now, "boot")
        attempts.append((run["trigger"], run["attempt"]))
    assert attempts == [("retry", 2), ("retry", 3)]
    assert env.store.get(aid)["retry_due_at"] is None


def test_success_resets_and_a_spending_target_is_never_retried(env, monkeypatch):
    auto = env.store.create(name="s", cron="0 3 * * *", target=ACTION, retry_max=3, retry_backoff_s=60)
    env.store.settle_retry(auto["automation_id"], True, env.clock.now)
    assert env.store.settle_retry(auto["automation_id"], False, env.clock.now) is None
    assert env.store.get(auto["automation_id"])["retry_due_at"] is None
    with pytest.raises(m.AutomationInvalid) as exc:
        env.store.create(name="p", cron="0 3 * * *", target={"kind": "recipe", "recipe": "scrooge"}, retry_max=1)
    assert exc.value.code == "retry_not_allowed"


def test_the_scheduler_arms_the_retry_and_caps_runtime(env, monkeypatch):
    monkeypatch.setattr(scheduler_module, "MAX_RUNTIME_GRACE_S", -59.9)
    auto = env.store.create(name="t", cron="0 3 * * *", target=ACTION, retry_max=1, retry_backoff_s=60, max_runtime_s=60)
    env.delay = 5.0

    async def go():
        sched = Scheduler(SimpleNamespace(), env.store, clock=env.clock)
        run = await sched.run_now(auto["automation_id"])
        await asyncio.gather(*sched._tasks)
        return env.store.run(run["run_id"])

    ended = asyncio.run(go())
    assert (ended["status"], ended["reason"]) == (m.FAILED, "max_runtime")
    assert env.told == [ended["run_id"]]
    assert env.store.get(auto["automation_id"])["retry_due_at"] == pytest.approx(env.clock.now + 60)


def test_a_runner_failure_is_retried_but_told_by_the_runner_not_the_scheduler(env):
    auto = env.store.create(name="u", cron="0 3 * * *", target=ACTION, retry_max=1, retry_backoff_s=60)

    async def go():
        sched = Scheduler(SimpleNamespace(), env.store, clock=env.clock)
        await sched.run_now(auto["automation_id"])
        await asyncio.gather(*sched._tasks)

    asyncio.run(go())
    assert env.told == []
    assert env.store.get(auto["automation_id"])["retry_due_at"] is not None


from __future__ import annotations

import asyncio
from types import SimpleNamespace

import src.config  # noqa: F401
from src.core.automations import scheduler as sched_mod
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for
from src.core.supervise import loop as sup


def test_a_typeerror_in_a_pass_does_not_end_the_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(sup, "DEFAULT_POLICY", sup.BackoffPolicy(initial_s=0.01, max_s=0.02))
    monkeypatch.setattr(sched_mod.run_sessions, "subscribe", lambda *a: None)
    scheduler = sched_mod.Scheduler(SimpleNamespace(), AutomationStore(storage_for(tmp_path)))
    passes = []
    boots = []

    async def pass_once():
        passes.append(1)
        if len(passes) == 1:
            raise TypeError("injected")
        return 0

    async def reconcile_spy(*a):
        boots.append(1)
        return []

    monkeypatch.setattr(scheduler, "pass_once", pass_once)
    monkeypatch.setattr(sched_mod.lifecycle, "reconcile_boot", lambda *a: boots.append(1) or [])

    async def go():
        task = asyncio.create_task(scheduler.run())
        for _ in range(200):
            if len(passes) >= 2:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(go())
    assert len(passes) >= 2
    assert boots == [1]


def test_a_typeerror_in_the_sweep_still_dispatches_the_claimed_runs(tmp_path, monkeypatch):
    scheduler = sched_mod.Scheduler(SimpleNamespace(), AutomationStore(storage_for(tmp_path)))
    dispatched = []

    async def sweep(*a):
        raise TypeError("injected")

    async def dispatch(run, by=None):
        dispatched.append(run["run_id"])
        return run["run_id"]

    monkeypatch.setattr(sched_mod.run_sessions, "sweep", sweep)
    monkeypatch.setattr(scheduler.store, "claim_due", lambda *a: [{"run_id": "r1", "automation_id": "a1"}])
    monkeypatch.setattr(scheduler, "_dispatch", dispatch)
    assert asyncio.run(scheduler.pass_once()) == 1
    assert dispatched == ["r1"]

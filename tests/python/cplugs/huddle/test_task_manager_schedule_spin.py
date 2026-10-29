from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.cplugs.huddle import schedule


def _scheduler(ran: int) -> schedule.Scheduler:
    sched = schedule.Scheduler(SimpleNamespace())

    async def run_checks_safe() -> int:
        return ran

    async def run_pass(events: bool, checks: bool) -> int:
        return 0

    sched._waits = SimpleNamespace(run_checks_safe=run_checks_safe, run_pass=run_pass)
    return sched


def _wake_after_batch(ran: int) -> bool:
    async def go() -> bool:
        sched = _scheduler(ran)
        sched._wake.clear()
        await sched.waits_due()
        await sched._check_task
        await asyncio.sleep(0)
        return sched._wake.is_set()

    return asyncio.run(go())


def test_an_empty_check_batch_does_not_wake_the_loop() -> None:
    assert _wake_after_batch(0) is False


def test_a_batch_that_ran_checks_wakes_the_loop() -> None:
    assert _wake_after_batch(2) is True

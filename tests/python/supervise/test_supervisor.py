
from __future__ import annotations

import asyncio
from typing import List

import pytest
from structlog.testing import capture_logs

from src.core.supervise import loop as sup

FAST = sup.BackoffPolicy(initial_s=0.01, max_s=0.04, factor=2.0, stable_after_s=999.0, degraded_after=3,
                         max_consecutive_failures=6, jitter=0.0)


def run(coro):
    return asyncio.run(coro)


def test_crashed_body_is_run_again_and_logged_with_its_name():
    calls: List[int] = []

    async def body():
        calls.append(1)
        if len(calls) < 3:
            raise TypeError("boom")

    with capture_logs() as logs:
        run(sup.supervise("t-restart", body, policy=FAST))
    assert len(calls) == 3
    crashes = [e for e in logs if e["event"] == "supervised_loop_crashed"]
    assert len(crashes) == 2 and all(e["loop"] == "t-restart" and e["error_type"] == "TypeError" for e in crashes)
    assert sup.loop_health()["t-restart"].restarts == 2


def test_a_loop_that_always_crashes_backs_off_to_the_cap_then_gives_up_loudly():
    pauses: List[float] = []

    async def fake_sleep(seconds):
        pauses.append(seconds)

    calls: List[int] = []

    async def body():
        calls.append(1)
        raise ValueError("always")

    with capture_logs() as logs:
        run(sup.supervise("t-cap", body, policy=FAST, sleep=fake_sleep))
    assert len(calls) == FAST.max_consecutive_failures
    assert pauses == [0.01, 0.02, 0.04, 0.04, 0.04]
    assert [e for e in logs if e["event"] == "supervised_loop_gave_up" and e["loop"] == "t-cap"]
    health = sup.loop_health()["t-cap"]
    assert health.gave_up and health.degraded and health.running is False


def test_the_pause_is_jittered_around_the_backoff():
    policy = sup.BackoffPolicy(initial_s=1.0, max_s=60.0, jitter=0.25)
    assert sup.jittered(4.0, policy, 0.0) == pytest.approx(3.0)
    assert sup.jittered(4.0, policy, 0.5) == pytest.approx(4.0)
    assert sup.jittered(4.0, policy, 1.0) == pytest.approx(5.0)


def test_a_clean_return_ends_the_supervisor_without_a_restart():
    calls: List[int] = []

    async def body():
        calls.append(1)

    run(sup.supervise("t-return", body, policy=FAST))
    assert calls == [1] and sup.loop_health()["t-return"].running is False


def test_cancel_passes_through_and_is_not_a_crash():
    async def body():
        await asyncio.sleep(60)

    async def go():
        task = sup.spawn("t-cancel", body, policy=FAST)
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with capture_logs() as logs:
        run(go())
    assert not [e for e in logs if e["event"] == "supervised_loop_crashed"]
    assert sup.loop_health()["t-cancel"].restarts == 0


def test_recovered_crash_and_degraded_log_at_warning_and_give_up_at_error_and_calls_back():
    policy = sup.BackoffPolicy(initial_s=0.001, max_s=0.002, degraded_after=2, max_consecutive_failures=3, jitter=0.0)
    called: List[int] = []

    async def body():
        raise ValueError("x")

    async def nosleep(_s):
        return None

    with capture_logs() as logs:
        asyncio.run(sup.supervise("lvl", body, policy=policy, sleep=nosleep, on_give_up=lambda: called.append(1)))
    levels = {e["event"]: e["log_level"] for e in logs}
    assert levels["supervised_loop_crashed"] == "warning"
    assert levels["supervised_loop_degraded"] == "warning"
    assert levels["supervised_loop_gave_up"] == "error"
    assert called == [1]


def test_cancel_during_the_backoff_sleep_stops_promptly():
    async def body():
        raise ValueError("x")

    async def go():
        task = asyncio.create_task(sup.supervise("cancel-sleep", body, policy=sup.BackoffPolicy(initial_s=30.0, max_s=30.0, jitter=0.0)))
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=1.0)
        return task.cancelled()

    assert asyncio.run(go()) is True
    assert sup.loop_health()["cancel-sleep"].running is False

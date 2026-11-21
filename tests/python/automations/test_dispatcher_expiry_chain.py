
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from structlog.testing import capture_logs

from src.core.crosstalk.delivery import dispatcher as disp


def test_a_failed_expiry_step_is_logged_and_the_timer_re_armed_with_a_doubling_pause():
    async def go():
        d = disp.Dispatcher(SimpleNamespace())

        async def boom():
            raise TypeError("injected")

        first = asyncio.get_running_loop().create_task(boom())
        await asyncio.gather(first, return_exceptions=True)
        d._expiry_task_done(first)
        armed = d._timer
        pause_after_first = d._expiry_pause
        second = asyncio.get_running_loop().create_task(boom())
        await asyncio.gather(second, return_exceptions=True)
        d._expiry_task_done(second)
        d._timer.cancel()
        return armed, pause_after_first, d._expiry_pause

    with capture_logs() as logs:
        armed, after_first, after_second = asyncio.run(go())
    assert armed is not None
    assert (after_first, after_second) == (disp.EXPIRY_RETRY_MIN_S * 2, disp.EXPIRY_RETRY_MIN_S * 4)
    assert [e for e in logs if e["event"] == "crosstalk_expiry_failed" and e["error_type"] == "TypeError"]


def test_expire_ok_then_a_failing_arm_keeps_doubling_and_close_stops_re_arming(monkeypatch):
    async def go():
        d = disp.Dispatcher(SimpleNamespace())

        async def ok():
            return None

        async def boom():
            raise TypeError("arm")

        done_ok = asyncio.get_running_loop().create_task(ok())
        await done_ok
        d._expiry_pause = disp.EXPIRY_RETRY_MIN_S * 4
        d._expiry_task_done(done_ok)
        kept = d._expiry_pause
        failed = asyncio.get_running_loop().create_task(boom())
        await asyncio.gather(failed, return_exceptions=True)
        d._expiry_task_done(failed)
        doubled = d._expiry_pause
        d._timer.cancel()
        d._timer = None
        d.close()
        d._expiry_task_done(failed)
        return kept, doubled, d._timer

    kept, doubled, timer = asyncio.run(go())
    assert kept == disp.EXPIRY_RETRY_MIN_S * 4
    assert doubled == disp.EXPIRY_RETRY_MIN_S * 8
    assert timer is None

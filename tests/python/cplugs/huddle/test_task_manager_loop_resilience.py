from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.cplugs.huddle import schedule, send_queue
from src.cplugs.huddle.roles import port as roles_port


def test_the_schedule_loop_survives_a_pass_that_raises_a_key_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(schedule, "MAX_SLEEP_S", 0.01)

    async def settle(ctx: object) -> None:
        return None

    monkeypatch.setattr(roles_port, "settle", settle)
    calls = {"n": 0}

    async def go() -> int:
        async def booted() -> None:
            return None

        sched = schedule.Scheduler(SimpleNamespace(sessions=SimpleNamespace(booted=booted)))

        async def fire_due() -> None:
            calls["n"] += 1
            raise KeyError("boom")

        sched.fire_due = fire_due  # type: ignore[method-assign]
        task = asyncio.get_running_loop().create_task(sched.run())
        await asyncio.sleep(0.2)
        alive = not task.done()
        task.cancel()
        assert alive, "the loop ended after the first failed pass"
        return calls["n"]

    assert asyncio.run(go()) >= 2


def test_a_failed_flush_puts_the_list_back_in_the_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    send_queue.use_clock(lambda: 100.0)
    monkeypatch.setattr(send_queue, "_arm", lambda ctx: None)
    monkeypatch.setattr(send_queue, "_push", lambda ctx: None)
    send_queue._queue.note("alpha")

    async def failing(ctx: object, key: str) -> None:
        send_queue._queue.drop(key)
        raise OSError("tmux gone")

    monkeypatch.setattr(send_queue, "flush_list", failing)
    out = asyncio.run(send_queue._flush_keys(SimpleNamespace(), ["alpha"]))
    assert out == []
    assert send_queue.is_queued("alpha")
    send_queue.reset()

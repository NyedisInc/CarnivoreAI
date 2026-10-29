
from __future__ import annotations

import asyncio

import pytest
from structlog.testing import capture_logs

from src.core.boot.teardown import TeardownRunner, stop_task


def _boom() -> None:
    raise RuntimeError("stop blew up")


@pytest.mark.asyncio
async def test_early_failure_does_not_skip_later_steps_and_logs_once() -> None:
    ran: list[str] = []

    async def late_async() -> None:
        ran.append("async")

    td = TeardownRunner()
    with capture_logs() as logs:
        await td.run("first", lambda: ran.append("first"))
        await td.run("early", _boom)
        await td.run("sync", lambda: ran.append("sync"))
        await td.run("async", late_async)
    assert ran == ["first", "sync", "async"]
    failures = [e for e in logs if e["event"] == "lifespan_teardown_step_failed"]
    assert len(failures) == 1
    assert failures[0]["step"] == "early" and failures[0]["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_gated_step_is_skipped_when_its_requirement_failed() -> None:
    ran: list[str] = []
    td = TeardownRunner()
    with capture_logs() as logs:
        await td.run("relay", _boom)
        await td.run("store", lambda: ran.append("store"), requires=("relay",))
        await td.run("after_store", lambda: ran.append("after_store"), requires=("store",))
        await td.run("independent", lambda: ran.append("independent"))
    assert ran == ["independent"]
    assert [e["step"] for e in logs if e["event"] == "lifespan_teardown_step_skipped"] == ["store", "after_store"]


@pytest.mark.asyncio
async def test_gated_step_runs_when_its_requirement_succeeded() -> None:
    ran: list[str] = []
    td = TeardownRunner()
    await td.run("a", lambda: ran.append("a"))
    assert await td.run("b", lambda: ran.append("b"), requires=("a",)) is True
    assert ran == ["a", "b"]


@pytest.mark.asyncio
async def test_cancellation_of_the_teardown_itself_propagates() -> None:
    def cancelled() -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await TeardownRunner().run("x", cancelled)


@pytest.mark.asyncio
async def test_stop_task_cancels_awaits_and_tolerates_none() -> None:
    task = asyncio.create_task(asyncio.sleep(60))
    await stop_task(task)
    assert task.cancelled()
    other = asyncio.create_task(asyncio.sleep(60))
    await stop_task(other, wait=False)
    assert other.cancelling() == 1
    await stop_task(None)
    with pytest.raises(asyncio.CancelledError):
        await other


@pytest.mark.asyncio
async def test_cancelling_the_teardown_while_it_waits_on_a_task_is_not_swallowed() -> None:
    inner = asyncio.create_task(asyncio.sleep(60))

    async def teardown() -> None:
        await stop_task(inner, cancel=False)

    outer = asyncio.create_task(teardown())
    await asyncio.sleep(0)
    outer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await outer
    assert outer.cancelled()
    await stop_task(asyncio.create_task(asyncio.sleep(60)))


@pytest.mark.asyncio
async def test_leftover_cancelling_count_does_not_make_stop_task_reraise() -> None:
    current = asyncio.current_task()
    assert current is not None
    current.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.sleep(0)
    assert current.cancelling() >= 1
    try:
        await stop_task(asyncio.create_task(asyncio.sleep(60)))
    finally:
        while current.cancelling():
            current.uncancel()


@pytest.mark.asyncio
async def test_failed_step_is_logged_at_warning() -> None:
    with capture_logs() as logs:
        await TeardownRunner().run("x", _boom)
    assert [e["log_level"] for e in logs] == ["warning"]

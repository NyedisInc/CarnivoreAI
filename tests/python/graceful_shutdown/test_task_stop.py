
import asyncio

from src.core.graceful_shutdown import task_stop
from src.core.graceful_shutdown.task_stop import cancel_and_await


def test_none_is_a_no_op():
    asyncio.run(cancel_and_await(None, "x_crashed"))


def test_running_task_is_cancelled():
    async def run():
        task = asyncio.create_task(asyncio.sleep(60))
        await cancel_and_await(task, "x_crashed")
        return task.cancelled()

    assert asyncio.run(run()) is True


def test_crashed_task_is_logged_not_raised(monkeypatch):
    seen = []
    monkeypatch.setattr(task_stop.logger, "warning", lambda event, **kw: seen.append((event, kw)))

    async def run():
        async def boom():
            await asyncio.sleep(0)
            raise ValueError("bad")

        task = asyncio.create_task(boom())
        await asyncio.sleep(0.01)
        await cancel_and_await(task, "x_crashed")

    asyncio.run(run())
    assert seen and seen[0][0] == "x_crashed" and seen[0][1]["error_type"] == "ValueError"

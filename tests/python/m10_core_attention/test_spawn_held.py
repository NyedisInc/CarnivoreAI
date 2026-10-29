
from __future__ import annotations

import asyncio
import gc

from src.core.attention.wiring_builders import spawn_held


def test_task_is_held_while_running_and_released_after() -> None:
    async def scenario() -> None:
        held: set = set()
        done: list = []
        gate = asyncio.Event()

        async def work() -> None:
            await gate.wait()

        task = spawn_held(work(), held, done.append)
        del task
        gc.collect()
        await asyncio.sleep(0)
        assert len(held) == 1
        gate.set()
        await asyncio.sleep(0.01)
        assert not held and len(done) == 1

    asyncio.run(scenario())

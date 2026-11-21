
from __future__ import annotations

import asyncio
import time
from typing import Any

MAX_LOOP_STALL_SECONDS = 0.2


async def max_stall_while(awaitable: Any) -> float:
    gaps: list[float] = []
    stop = asyncio.Event()

    async def ticker() -> None:
        last = time.monotonic()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.05)
    await awaitable
    stop.set()
    await task
    return max(gaps)

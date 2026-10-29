
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional, Tuple

import structlog

from src.core.resource_push import notifier, topics

logger = structlog.get_logger()

TICK_SECONDS: float = 1.0
LEASE_SECONDS: float = 45.0
KEEPALIVE_SECONDS: float = 20.0


def file_signature(path: Path) -> Optional[Tuple[int, int]]:
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_size, info.st_mtime_ns)


class ServerLogWatch:

    def __init__(
        self,
        locate: Callable[[], Path],
        *,
        notify: Callable[[str], None] = notifier.notify,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._locate = locate
        self._notify = notify
        self._sleep = sleep
        self._clock = clock
        self._lease_until = 0.0
        self._task: Optional["asyncio.Task[None]"] = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def touch(self) -> None:
        self._lease_until = self._clock() + LEASE_SECONDS
        if not self.running:
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        last_sig = file_signature(self._locate())
        last_named = self._clock()
        while self._clock() < self._lease_until:
            await self._sleep(TICK_SECONDS)
            if self._clock() >= self._lease_until:
                break
            sig = file_signature(self._locate())
            if sig != last_sig or self._clock() - last_named >= KEEPALIVE_SECONDS:
                last_sig, last_named = sig, self._clock()
                self._notify(topics.SERVER_LOG)
        logger.debug("server_log_watch_idle")

    async def stop(self) -> None:
        self._lease_until = 0.0
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

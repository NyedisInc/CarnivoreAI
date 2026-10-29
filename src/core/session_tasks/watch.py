
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog
from pydantic import BaseModel

from src.core.resource_push import notifier, topics

logger = structlog.get_logger()

TICK_SECONDS: float = 3.0
LEASE_SECONDS: float = 45.0
KEEPALIVE_SECONDS: float = 20.0
ALL_KEY: str = "*"

Loader = Callable[[], Awaitable[BaseModel]]


@dataclass
class _Viewer:

    load: Loader
    lease_until: float
    last_sig: Optional[str] = None
    last_named: float = 0.0


class SessionTasksWatch:

    def __init__(self, *, notify: Callable[[str], None] = notifier.notify,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._notify, self._sleep, self._clock = notify, sleep, clock
        self._viewers: Dict[str, _Viewer] = {}
        self._task: Optional["asyncio.Task[None]"] = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def read(self, key: str, load: Loader) -> Any:
        now = self._clock()
        viewer = self._viewers.get(key)
        if viewer is None:
            viewer = self._viewers[key] = _Viewer(load, now + LEASE_SECONDS)
        viewer.load, viewer.lease_until = load, now + LEASE_SECONDS
        if not self.running:
            self._task = asyncio.get_running_loop().create_task(self._run())
        result = await load()
        viewer.last_sig, viewer.last_named = result.model_dump_json(), self._clock()
        return result

    async def _tick(self) -> bool:
        now = self._clock()
        self._viewers = {k: v for k, v in self._viewers.items() if v.lease_until > now}
        for key, viewer in list(self._viewers.items()):
            try:
                sig = (await viewer.load()).model_dump_json()
            except (OSError, RuntimeError, ValueError) as exc:
                logger.warning("session_tasks_watch_read_failed", key=key, error=type(exc).__name__)
                continue
            if viewer.last_sig is None or sig != viewer.last_sig or self._clock() - viewer.last_named >= KEEPALIVE_SECONDS:
                viewer.last_sig, viewer.last_named = sig, self._clock()
                self._notify(topics.keyed(topics.SESSION_TASKS, key))
        return bool(self._viewers)

    async def _run(self) -> None:
        while True:
            await self._sleep(TICK_SECONDS)
            try:
                if not await self._tick():
                    break
            except Exception as exc:  # noqa: BLE001
                logger.warning("session_tasks_watch_tick_failed", error=type(exc).__name__)

    async def stop(self) -> None:
        self._viewers.clear()
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

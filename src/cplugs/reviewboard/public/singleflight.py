
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Dict, Generic, Hashable, TypeVar

T = TypeVar("T")


class SingleFlight(Generic[T]):

    def __init__(self) -> None:
        self._running: Dict[Hashable, "asyncio.Future[T]"] = {}

    async def run(self, key: Hashable, work: Callable[[], Awaitable[T]]) -> T:
        running = self._running.get(key)
        if running is None:
            running = asyncio.ensure_future(work())
            self._running[key] = running
            running.add_done_callback(lambda done: self._finish(key, done))
        return await asyncio.shield(running)

    def _finish(self, key: Hashable, done: "asyncio.Future[T]") -> None:
        if self._running.get(key) is done:
            del self._running[key]
        if not done.cancelled():
            done.exception()

    def __len__(self) -> int:
        return len(self._running)

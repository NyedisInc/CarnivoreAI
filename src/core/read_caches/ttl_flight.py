from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Generic, Optional, TypeVar

from src.core.single_flight import SingleFlight

T = TypeVar("T")

_ALL: "list[TtlFlight[Any]]" = []


def invalidate_all() -> None:
    for cache in _ALL:
        cache.invalidate()


class TtlFlight(Generic[T]):

    def __init__(self, name: str, ttl: float = 1.0) -> None:
        self.ttl = ttl
        self.computations = 0
        self._flight: SingleFlight[Any] = SingleFlight(name)
        self._value: Optional[T] = None
        self._at = float("-inf")
        self._generation = 0
        _ALL.append(self)

    def invalidate(self) -> None:
        self._generation += 1
        self._at = float("-inf")
        self._value = None

    async def get(self, work: Callable[[], Awaitable[T]]) -> T:
        now = time.monotonic()
        if self._value is not None and now - self._at < self.ttl:
            return self._value
        generation = self._generation

        async def run() -> T:
            self.computations += 1
            started = time.monotonic()
            value = await work()
            if generation == self._generation:
                self._value, self._at = value, started
            return value

        return await self._flight.run(run)

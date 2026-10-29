from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Generic, Optional, TypeVar

import structlog

logger = structlog.get_logger()

T = TypeVar("T")

SESSION_LIST_FLIGHT_ATTR = "_session_list_flight"

SESSION_LIST_FLIGHT_NAME = "sessions_list"


class _Flight:

    __slots__ = ("task", "callers")

    def __init__(self, task: "asyncio.Task[Any]") -> None:
        self.task = task
        self.callers = 0


class SingleFlight(Generic[T]):

    def __init__(self, name: str) -> None:
        self._name = name
        self._flight: Optional[_Flight] = None
        self.passes_started = 0
        self.callers_served = 0
        self.callers_coalesced = 0

    @property
    def in_flight(self) -> bool:
        return self._flight is not None and not self._flight.task.done()

    async def run(self, work: Callable[[], Awaitable[T]]) -> T:
        flight = self._flight
        if flight is None or flight.task.done():
            flight = _Flight(task=asyncio.ensure_future(work()))
            self._flight = flight
            self.passes_started += 1
            flight.task.add_done_callback(self._retire)
        else:
            self.callers_coalesced += 1
        flight.callers += 1
        self.callers_served += 1
        return await asyncio.shield(flight.task)

    def _retire(self, task: "asyncio.Task[Any]") -> None:
        flight = self._flight
        if flight is not None and flight.task is task:
            self._flight = None
        callers = flight.callers if flight is not None else 0
        if task.cancelled():
            logger.debug(
                "single_flight_cancelled", flight=self._name, callers=callers
            )
            return
        error = task.exception()
        if error is not None:
            logger.debug(
                "single_flight_failed",
                flight=self._name,
                callers=callers,
                error=str(error),
                error_type=type(error).__name__,
            )
            return
        if callers > 1:
            logger.debug(
                "single_flight_coalesced",
                flight=self._name,
                callers=callers,
                passes_saved=callers - 1,
            )


def flight_on(owner: Any, attr: str, name: str) -> SingleFlight[Any]:
    existing = getattr(owner, attr, None)
    if isinstance(existing, SingleFlight):
        return existing
    created: SingleFlight[Any] = SingleFlight(name)
    setattr(owner, attr, created)
    return created

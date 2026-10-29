
from __future__ import annotations

import asyncio
import inspect
from typing import Awaitable, Callable, Optional, Union

import structlog

logger = structlog.get_logger()

Step = Callable[[], Union[None, Awaitable[None]]]


async def stop_task(task: Optional["asyncio.Future[object]"], *, cancel: bool = True, wait: bool = True) -> None:
    if task is None:
        return
    if cancel:
        task.cancel()
    if wait:
        current = asyncio.current_task()
        cancelling_before = current.cancelling() if current is not None else 0
        try:
            await task
        except asyncio.CancelledError:
            if current is not None and current.cancelling() > cancelling_before:
                raise


class TeardownRunner:

    def __init__(self, log: Optional[structlog.stdlib.BoundLogger] = None) -> None:
        self._log = log or logger
        self.failed: set[str] = set()

    async def run(self, name: str, step: Step, *, requires: tuple[str, ...] = ()) -> bool:
        blocked_by = [dep for dep in requires if dep in self.failed]
        if blocked_by:
            self.failed.add(name)
            self._log.warning("lifespan_teardown_step_skipped", step=name, blocked_by=blocked_by)
            return False
        try:
            result = step()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001
            self.failed.add(name)
            self._log.warning("lifespan_teardown_step_failed", step=name, error_type=type(exc).__name__, error=str(exc), exc_info=True)
            return False
        return True

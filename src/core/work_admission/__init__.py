from __future__ import annotations

import asyncio
import enum
from typing import Any, Callable, Dict, Optional, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class WorkClass(str, enum.Enum):

    INTERACTIVE = "interactive"
    RECONCILE = "reconcile"
    BULK_SCAN = "bulk_scan"
    EXPORT = "export"
    BACKGROUND = "background"


LIMITS: Dict[WorkClass, int] = {
    WorkClass.RECONCILE: 2,
    WorkClass.BULK_SCAN: 2,
    WorkClass.EXPORT: 2,
    WorkClass.BACKGROUND: 2,
}


class AdmissionRefused(Exception):

    def __init__(self, work_class: WorkClass, limit: int, waited: Optional[float]):
        super().__init__(
            f"{limit} {work_class.value} jobs already in flight"
            + (f" and none finished within {waited}s" if waited is not None else "")
        )
        self.work_class = work_class
        self.limit = limit


class Permit:

    __slots__ = ("_release",)

    def __init__(self, release: Callable[[], None]):
        self._release: Optional[Callable[[], None]] = release

    def release(self) -> None:
        release, self._release = self._release, None
        if release is not None:
            release()


class Admission:

    def __init__(self, limits: Optional[Dict[WorkClass, int]] = None):
        self._limits = dict(LIMITS if limits is None else limits)
        self._sems: Dict[WorkClass, asyncio.Semaphore] = {}
        self._held: Dict[WorkClass, int] = {c: 0 for c in WorkClass}

    def limit(self, work_class: WorkClass) -> Optional[int]:
        return self._limits.get(work_class)

    def in_flight(self, work_class: WorkClass) -> int:
        return self._held[work_class]

    def _sem(self, work_class: WorkClass) -> asyncio.Semaphore:
        sem = self._sems.get(work_class)
        if sem is None:
            sem = self._sems[work_class] = asyncio.Semaphore(self._limits[work_class])
        return sem

    def _give_back(self, work_class: WorkClass) -> None:
        self._held[work_class] -= 1
        sem = self._sems.get(work_class)
        if sem is not None:
            sem.release()

    async def acquire(self, work_class: WorkClass, timeout: Optional[float] = None) -> Permit:
        if work_class not in self._limits:
            self._held[work_class] += 1
            return Permit(lambda: self._held.__setitem__(work_class, self._held[work_class] - 1))
        try:
            await asyncio.wait_for(self._sem(work_class).acquire(), timeout=timeout)
        except asyncio.TimeoutError:
            raise AdmissionRefused(work_class, self._limits[work_class], timeout) from None
        self._held[work_class] += 1
        return Permit(lambda: self._give_back(work_class))

    async def run(
        self,
        work_class: WorkClass,
        fn: Callable[..., T],
        *args: Any,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> T:
        permit = await self.acquire(work_class, timeout)
        try:
            task = asyncio.ensure_future(asyncio.to_thread(fn, *args, **kwargs))
        except BaseException:
            permit.release()
            raise
        task.add_done_callback(lambda t: self._finish(t, permit, work_class))
        return await asyncio.shield(task)

    @staticmethod
    def _finish(task: "asyncio.Future[Any]", permit: Permit, work_class: WorkClass) -> None:
        permit.release()
        if not task.cancelled() and task.exception() is not None:
            logger.debug("admitted_work_failed", work_class=work_class.value,
                         error=repr(task.exception()))


admission = Admission()

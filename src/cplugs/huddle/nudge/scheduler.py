
from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional

import structlog

from src.cplugs.huddle import service, triggers
from src.cplugs.huddle.nudge import planning, settings, sweep
from src.cplugs.huddle.nudge_store import NudgeStore
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

MAX_SLEEP_S = 300.0
MIN_SLEEP_S = 0.05


class Scheduler:

    def __init__(self, ctx: CplugContext, clock: Callable[[], float] = time.time) -> None:
        self._ctx = ctx
        self._clock = clock
        self._wake = asyncio.Event()
        self._next_sweep = 0.0

    def poke(self) -> None:
        self._wake.set()

    def _armed(self) -> bool:
        return settings.read(self._ctx.settings_now()).enabled and NudgeStore(service.store(self._ctx)).enabled()

    async def due(self) -> bool:
        if self._clock() < self._next_sweep:
            return False
        if not await asyncio.to_thread(self._armed):
            self._next_sweep = 0.0
            return False
        minutes = await sweep.sweep(self._ctx, self._clock)
        self._next_sweep = self._clock() + planning.sweep_period_s(minutes)
        return True

    def _timeout(self) -> Optional[float]:
        if not self._armed():
            self._next_sweep = 0.0
            return None
        return min(max(self._next_sweep - self._clock(), MIN_SLEEP_S), MAX_SLEEP_S)

    async def run(self) -> None:
        try:
            await self._ctx.sessions.booted()
        except (OSError, RuntimeError, AttributeError) as exc:
            logger.warning("nudge_boot_wait_failed", error=str(exc))
        while True:
            self._wake.clear()
            try:
                await self.due()
                timeout = await asyncio.to_thread(self._timeout)
            except Exception as exc:  # noqa: BLE001
                logger.exception("nudge_pass_failed", error_type=type(exc).__name__, error=str(exc)[:200])
                timeout = MAX_SLEEP_S
            try:
                await asyncio.wait_for(self._wake.wait(), timeout)
            except asyncio.TimeoutError:
                pass


class Running:

    task: Optional["asyncio.Task[None]"] = None
    unsubscribe: list = []
    scheduler: Optional[Scheduler] = None


def start(ctx: CplugContext, clock: Callable[[], float] = time.time) -> None:
    stop()
    scheduler = Running.scheduler = Scheduler(ctx, clock)
    loop = asyncio.get_running_loop()

    def poke() -> None:
        try:
            loop.call_soon_threadsafe(scheduler.poke)
        except RuntimeError as exc:
            logger.debug("nudge_poke_loop_closed", error=str(exc))

    Running.unsubscribe = [triggers.subscribe(poke), triggers.subscribe_writes(poke)]
    poke()
    Running.task = loop.create_task(scheduler.run(), name="nudge-scheduler")


def settings_saved() -> None:
    if Running.scheduler is not None:
        Running.scheduler.poke()


def stop() -> None:
    Running.scheduler = None
    for undo in Running.unsubscribe:
        undo()
    Running.unsubscribe = []
    if Running.task is not None:
        Running.task.cancel()
        Running.task = None

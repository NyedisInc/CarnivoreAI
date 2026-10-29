
from __future__ import annotations

import asyncio
import subprocess
import time
from typing import Awaitable, Callable, Dict, Optional

import structlog

from src.core.machine_stats.sample import MachineSampler, signature
from src.core.resource_push import notifier, topics

logger = structlog.get_logger()

TICK_SECONDS: float = 5.0
LEASE_SECONDS: float = 45.0
KEEPALIVE_SECONDS: float = 20.0


class MachineStatsWatch:

    def __init__(
        self,
        sampler: MachineSampler,
        *,
        notify=notifier.notify,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.sampler = sampler
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
        last_sig = None
        last_named = self._clock()
        while self._clock() < self._lease_until:
            await self._sleep(TICK_SECONDS)
            if self._clock() >= self._lease_until:
                break
            try:
                reading: Dict = await asyncio.to_thread(self.sampler.read, 0.0)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                logger.warning("machine_stats_sample_failed", error=str(exc))
                continue
            sig = signature(reading)
            if sig != last_sig or self._clock() - last_named >= KEEPALIVE_SECONDS:
                last_sig, last_named = sig, self._clock()
                self._notify(topics.MACHINE_STATS)
        self.sampler.reset_cpu_baseline()
        logger.debug("machine_stats_sampler_idle")

    async def stop(self) -> None:
        self._lease_until = 0.0
        self.sampler.reset_cpu_baseline()
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

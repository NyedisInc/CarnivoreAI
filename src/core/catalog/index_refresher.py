
from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable, Optional

import structlog

from src.core.catalog.index_cache import IndexCache
from src.core.catalog import publisher_rename, theme_migration
from src.core.catalog.index_freshness import SCHEDULED_REFRESH_SECONDS

logger = structlog.get_logger()

FIRST_RUN_DELAY_RANGE = (20.0, 120.0)
JITTER_RANGE = (0.9, 1.1)
FAILURE_BASE_SECONDS = 15 * 60.0

HOURLY_SECONDS = 3600.0


def next_wait(failures: int, *, jitter: float) -> float:
    if failures <= 0:
        return SCHEDULED_REFRESH_SECONDS * jitter
    backoff = FAILURE_BASE_SECONDS * (2 ** (failures - 1))
    return min(backoff, SCHEDULED_REFRESH_SECONDS) * jitter


class IndexRefresher:

    def __init__(
        self,
        cache: IndexCache,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Optional[random.Random] = None,
        services: Any = None,
    ) -> None:
        self._cache = cache
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._services = services
        self._task: Optional["asyncio.Task[None]"] = None
        self.failures = 0
        self.hourly_while: Optional[Callable[[], bool]] = None
        self.after_pass: Optional[Callable[[Any], Awaitable[None]]] = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def run_pass(self) -> bool:
        snapshot, attempted = await self._cache.refresh_if_due()
        ok = snapshot.refusal is None
        if attempted:
            self.failures = 0 if ok else self.failures + 1
            logger.info("catalog_index_scheduled_pass", ok=ok, failures=self.failures)
        await self._apply_publisher_rename(snapshot)
        await self._apply_theme_migration(snapshot)
        await self.notify_after_pass(snapshot)
        return ok

    async def notify_after_pass(self, snapshot: Any) -> None:
        if self.after_pass is None:
            return
        try:
            await self.after_pass(snapshot)
        except Exception as exc:  # noqa: BLE001
            logger.warning("catalog_index_after_pass_failed", error=str(exc))

    def _wait(self) -> float:
        return next_wait(self.failures, jitter=self._rng.uniform(*JITTER_RANGE))

    async def _sleep_until_due(self) -> None:
        remaining = self._wait()
        if self.hourly_while is None:
            await self._sleep(remaining)
            return
        while remaining > 0:
            step = min(remaining, HOURLY_SECONDS)
            await self._sleep(step)
            remaining -= step
            if remaining > 0 and self.hourly_while():
                return

    async def _apply_publisher_rename(self, snapshot: Any) -> None:
        if self._services is None:
            return
        try:
            await asyncio.to_thread(publisher_rename.apply, snapshot, self._services)
        except Exception as exc:  # noqa: BLE001
            logger.warning("catalog_publisher_rename_pass_failed", error=str(exc))

    async def _apply_theme_migration(self, snapshot: Any) -> None:
        if self._services is None:
            return
        try:
            await theme_migration.run(snapshot, self._services)
        except Exception as exc:  # noqa: BLE001
            logger.warning("catalog_theme_migration_pass_failed", error=str(exc))

    async def _run(self) -> None:
        await self._sleep(self._rng.uniform(*FIRST_RUN_DELAY_RANGE))
        while True:
            try:
                await self.run_pass()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.failures += 1
                logger.warning("catalog_index_scheduled_pass_failed", error=str(exc))
            await self._sleep_until_due()


from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional

import structlog

from src.cplugs.save.pipeline_row import RECORD
from src.cplugs.save.service import RUNTIME
from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault.follow import SliceResult

logger = structlog.get_logger()


STOP_WAIT_SECONDS: float = 60.0


class Follower:

    def __init__(self, slice_fn: Optional[Callable[[], SliceResult]] = None, period: float = K.FOLLOW_SECONDS,
                 retry: float = K.BACKFILL_RETRY_SECONDS, cancel: Optional[Callable[[], None]] = None) -> None:
        self._slice = slice_fn or (lambda: RUNTIME.engine().run_slice())
        self._cancel = cancel or RUNTIME.cancel
        self._period, self._retry = period, retry
        self._task: Optional[asyncio.Task] = None
        self._work: Optional[asyncio.Future] = None

    async def once(self) -> SliceResult:
        timer = time.monotonic()
        self._work = asyncio.ensure_future(asyncio.to_thread(self._slice))
        result = await asyncio.shield(self._work)
        RECORD.record_pass(written=result.captured, failed=result.failed, duration_s=time.monotonic() - timer,
                           error="vault_unavailable" if result.unavailable else None)
        return result

    async def _loop(self) -> None:
        while True:
            pause = self._period
            try:
                pause = self._retry if (await self.once()).more else self._period
            except (OSError, RuntimeError) as exc:
                logger.error("save_follower_failed", error=str(exc), error_type=type(exc).__name__)
                RECORD.record_pass(written=0, failed=0, duration_s=0.0, error=type(exc).__name__)
            await asyncio.sleep(pause)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._loop(), name="save-vault-follower")

    async def stop(self, wait: float = STOP_WAIT_SECONDS) -> None:
        self._cancel()
        task, work, self._task = self._task, self._work, None
        if task is not None:
            task.cancel()
        if work is not None and not work.done():
            done, _pending = await asyncio.wait([work], timeout=wait)
            if not done:
                logger.warning("save_follower_slice_still_running", waited=wait)
            elif work.exception() is not None:
                logger.warning("save_follower_slice_ended_with_error", error=str(work.exception()))

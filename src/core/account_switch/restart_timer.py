
from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, Awaitable, Callable, Optional

import structlog

from src.models.provider_ledger import LedgerSnapshot

logger = structlog.get_logger()

TICK_SECONDS = 15.0

STOP_GRACE_SECONDS = 20.0


async def _default_pass(snapshot: LedgerSnapshot, app_state: Any) -> Any:
    from src.core.account_switch import auto_restart

    return await auto_restart.after_pass(snapshot, app_state)


class RestartTimer:

    def __init__(
        self,
        *,
        app_state: Any,
        snapshot: Callable[[], LedgerSnapshot],
        run_pass: Callable[[LedgerSnapshot, Any], Awaitable[Any]] = _default_pass,
        tick_seconds: float = TICK_SECONDS,
    ) -> None:
        self._app_state = app_state
        self._snapshot = snapshot
        self._run_pass = run_pass
        self._tick_seconds = tick_seconds
        self._task: Optional[asyncio.Task] = None
        self._wake = asyncio.Event()
        self._stopping = False

    def start(self) -> bool:
        if self._task is not None and not self._task.done():
            return False
        self._stopping = False
        self._wake = asyncio.Event()
        self._task = asyncio.create_task(self._loop())
        logger.info("auto_restart_timer_started", tick_seconds=self._tick_seconds)
        return True

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        task, self._task = self._task, None
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), STOP_GRACE_SECONDS)
        except asyncio.TimeoutError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        logger.info("auto_restart_timer_stopped")

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self._run_pass(self._snapshot(), self._app_state)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("auto_restart_timer_pass_failed", error=type(exc).__name__)
            if self._stopping:
                break
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self._tick_seconds)


from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event
from typing import Any, Dict, Optional

import structlog

from src.core.work_admission import WorkClass, admission
from src.core.db_integrity import (
    ENABLE_ENV,
    integrity_check_enabled,
    latest_path,
    resolve_interval_seconds,
    resolve_stale_after_seconds,
    run_integrity_check_once,
    seconds_until_due,
)

logger = structlog.get_logger()


class DatabaseIntegrityScheduler:

    def __init__(
        self, state_dir: Path, *, interval_seconds: Optional[int] = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.interval_seconds = (
            interval_seconds if interval_seconds is not None
            else resolve_interval_seconds()
        )
        self.enabled = integrity_check_enabled()
        self.last_record: Optional[Dict[str, Any]] = None
        self.runs_completed = 0
        self._cancel = Event()
        self._task: Optional[asyncio.Task] = None

    def start(self) -> bool:
        if not self.enabled:
            logger.info("db_integrity_disabled", env=ENABLE_ENV)
            return False
        if self._task is not None and not self._task.done():
            return False
        self._cancel.clear()
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "db_integrity_scheduler_started",
            interval_seconds=self.interval_seconds,
            stale_after_seconds=resolve_stale_after_seconds(
                self.interval_seconds
            ),
        )
        return True

    async def _loop(self) -> None:
        initial = seconds_until_due(self.state_dir, self.interval_seconds)
        if initial > 0:
            logger.info(
                "db_integrity_check_not_due",
                seconds_until_due=round(initial, 1),
                artifact=str(latest_path(self.state_dir)),
            )
            await asyncio.sleep(initial)
        while not self._cancel.is_set():
            try:
                record = await admission.run(
                    WorkClass.BACKGROUND,
                    run_integrity_check_once,
                    self.state_dir,
                    cancel=self._cancel,
                )
                self.last_record = record
                self.runs_completed += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "db_integrity_check_crashed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            if self._cancel.is_set():
                break
            await asyncio.sleep(self.interval_seconds)

    async def aclose(self, timeout: float = 10.0) -> None:
        self._cancel.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(_swallow(task)), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            logger.warning("db_integrity_scheduler_stop_timeout")
        logger.info("db_integrity_scheduler_stopped")

    def status(self) -> Dict[str, Any]:
        running = self._task is not None and not self._task.done()
        return {
            "enabled": self.enabled,
            "running": running,
            "interval_seconds": self.interval_seconds,
            "runs_completed_this_process": self.runs_completed,
            "cancel_requested": self._cancel.is_set(),
            "artifact": str(latest_path(self.state_dir)),
        }


async def _swallow(task: asyncio.Task) -> None:
    try:
        await task
    except asyncio.CancelledError:
        return

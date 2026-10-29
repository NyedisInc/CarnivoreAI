
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Iterable, Optional

import structlog

from src.core.hosts.identity import is_remote_info

logger = structlog.get_logger()

RESWEEP_INTERVAL_SECONDS: float = 60.0


def _default_sweep(session_manager: Any) -> Any:
    from src.core.session_agent_infer_sweep import sweep_live_sessions

    return sweep_live_sessions(session_manager)


class AgentResweep:

    def __init__(
        self,
        *,
        interval: float = RESWEEP_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sweep: Callable[[Any], Any] = _default_sweep,
    ) -> None:
        self._interval = float(interval)
        self._clock = clock
        self._sweep = sweep
        self._last_start: Optional[float] = None
        self._task: Optional["asyncio.Future[Any]"] = None

    def maybe_schedule(
        self, session_manager: Any, infos: Iterable[Any]
    ) -> Optional["asyncio.Future[Any]"]:
        boot = session_manager._boot_readopt_task
        if boot is None or not boot.done():
            return None
        if not any(info.agent_family is None and not is_remote_info(info) for info in infos):
            return None
        if self._task is not None and not self._task.done():
            return None
        now = self._clock()
        if self._last_start is not None and now - self._last_start < self._interval:
            return None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        self._last_start = now
        self._task = loop.create_task(self._run(session_manager))
        return self._task

    async def _run(self, session_manager: Any) -> None:
        try:
            examined, written = await asyncio.to_thread(self._sweep, session_manager)
            logger.info(
                "agent_infer_resweep_complete", examined=examined, written=written
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent_infer_resweep_failed", error=str(exc))

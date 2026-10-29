
from __future__ import annotations

import asyncio
import subprocess
from typing import Any, Optional

import structlog

from src.cplugs.sdk import CapabilityMissing
from src.cplugs.timemachine import constants as K
from src.cplugs.timemachine import service

logger = structlog.get_logger()
_task: Optional[asyncio.Task] = None


async def _loop(ctx: Any) -> None:
    await asyncio.sleep(K.FIRST_PASS_DELAY_S)
    while True:
        try:
            await asyncio.to_thread(service.run_pass, ctx)
        except (CapabilityMissing, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            logger.error("timemachine_pass_failed", error=str(exc), error_type=type(exc).__name__)
        await asyncio.sleep(K.PERIOD_S)


def start(ctx: Any) -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_loop(ctx), name="timemachine-check")


async def stop() -> None:
    global _task
    task, _task = _task, None
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

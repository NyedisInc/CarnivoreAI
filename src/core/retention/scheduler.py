
from __future__ import annotations

import asyncio
import threading

import structlog

from src.core.retention import constants as K
from src.core.retention.service import RetentionService, get_service

logger = structlog.get_logger()


async def run_forever(service: RetentionService | None = None, startup_delay: float = K.STARTUP_DELAY_SECONDS) -> None:
    svc = service or get_service()
    stop = threading.Event()
    try:
        await asyncio.sleep(startup_delay)
        while True:
            cfg = svc.config()
            if cfg.enabled:
                from src.core.perf_hooks import executors as _executors

                await _executors.run_in(_executors.maintenance_executor(), svc.run, False, stop.is_set)
            await asyncio.sleep(cfg.interval_seconds)
    finally:
        stop.set()

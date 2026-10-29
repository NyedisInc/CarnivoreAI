
from __future__ import annotations

import asyncio

import structlog

logger = structlog.get_logger(__name__)


async def cancel_and_await(task: "asyncio.Task | None", crash_event: str) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning(crash_event, error=str(exc), error_type=type(exc).__name__)

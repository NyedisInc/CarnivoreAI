
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

import structlog

logger = structlog.get_logger()

FIRST_BACKOFF_SECONDS: float = 0.5
MAX_BACKOFF_SECONDS: float = 15.0
HEALTHY_RUN_SECONDS: float = 30.0

RETRYABLE: tuple[type[BaseException], ...] = (OSError, ValueError)


def next_backoff(previous: float) -> float:
    return min(MAX_BACKOFF_SECONDS, max(FIRST_BACKOFF_SECONDS, previous * 2))


async def supervise_tail(
    run_once: Callable[[], Awaitable[None]],
    *,
    is_running: Callable[[], bool],
    session: str,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    pause = 0.0
    while is_running():
        started = time.monotonic()
        try:
            await run_once()
            reason = "returned"
        except RETRYABLE as exc:
            reason = type(exc).__name__
            logger.error("tmux_tail_loop_crashed", session=session, error=str(exc))
        if not is_running():
            return
        pause = 0.0 if time.monotonic() - started >= HEALTHY_RUN_SECONDS else next_backoff(pause)
        logger.warning("tmux_tail_loop_restarting", session=session, reason=reason, pause=pause)
        await sleep(pause)

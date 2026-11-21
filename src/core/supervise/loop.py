
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, replace
from typing import Awaitable, Callable, Dict, Optional

import structlog

logger = structlog.get_logger()


@dataclass(frozen=True)
class BackoffPolicy:

    initial_s: float = 1.0
    max_s: float = 60.0
    factor: float = 2.0
    stable_after_s: float = 60.0
    degraded_after: int = 5
    max_consecutive_failures: int = 10
    jitter: float = 0.25


DEFAULT_POLICY = BackoffPolicy()


@dataclass
class LoopHealth:

    name: str
    running: bool = False
    restarts: int = 0
    consecutive_failures: int = 0
    degraded: bool = False
    gave_up: bool = False
    last_error: Optional[str] = None
    last_error_at: Optional[float] = None


_HEALTH: Dict[str, LoopHealth] = {}


def loop_health() -> Dict[str, LoopHealth]:
    return {name: replace(item) for name, item in _HEALTH.items()}


def next_pause(current: float, policy: BackoffPolicy) -> float:
    return min(policy.max_s, max(policy.initial_s, current * policy.factor))


def jittered(pause: float, policy: BackoffPolicy, unit: float) -> float:
    return pause * (1.0 - policy.jitter + 2.0 * policy.jitter * unit)


def _record_crash(health: LoopHealth, exc: Exception, pause: float, policy: BackoffPolicy) -> None:
    health.restarts += 1
    health.consecutive_failures += 1
    health.last_error = f"{type(exc).__name__}: {exc}"[:300]
    health.last_error_at = time.time()
    newly_degraded = health.consecutive_failures >= policy.degraded_after and not health.degraded
    health.degraded = health.degraded or newly_degraded
    logger.warning("supervised_loop_crashed", loop=health.name, error_type=type(exc).__name__, error=str(exc)[:300],
                 restarts=health.restarts, consecutive_failures=health.consecutive_failures, retry_in_s=round(pause, 2),
                 exc_info=exc)
    if newly_degraded:
        logger.warning("supervised_loop_degraded", loop=health.name, consecutive_failures=health.consecutive_failures)


def _notify_give_up(name: str, on_give_up: Optional[Callable[[], None]]) -> None:
    if on_give_up is None:
        return
    try:
        on_give_up()
    except Exception as exc:
        logger.error("supervised_loop_give_up_callback_failed", loop=name, error_type=type(exc).__name__, exc_info=exc)


async def supervise(name: str, body: Callable[[], Awaitable[None]], *, policy: Optional[BackoffPolicy] = None,
                    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                    draw: Callable[[], float] = random.random,
                    on_give_up: Optional[Callable[[], None]] = None) -> None:
    policy = policy or DEFAULT_POLICY
    health = _HEALTH[name] = LoopHealth(name=name, running=True)
    pause = policy.initial_s
    try:
        while True:
            started = time.monotonic()
            try:
                await body()
                return
            except Exception as exc:
                if time.monotonic() - started >= policy.stable_after_s:
                    pause, health.consecutive_failures, health.degraded = policy.initial_s, 0, False
                wait = jittered(pause, policy, draw())
                _record_crash(health, exc, wait, policy)
            if health.consecutive_failures >= policy.max_consecutive_failures:
                health.gave_up = True
                logger.error("supervised_loop_gave_up", loop=name, consecutive_failures=health.consecutive_failures,
                             last_error=health.last_error)
                _notify_give_up(name, on_give_up)
                return
            await sleep(wait)
            pause = next_pause(pause, policy)
    finally:
        health.running = False


def spawn(name: str, body: Callable[[], Awaitable[None]], *, policy: Optional[BackoffPolicy] = None,
          on_give_up: Optional[Callable[[], None]] = None) -> "asyncio.Task[None]":
    return asyncio.get_running_loop().create_task(supervise(name, body, policy=policy, on_give_up=on_give_up), name=name)


from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Optional

import structlog

from src.core.resource_push.topics import family_of

logger = structlog.get_logger()

MAX_BODY_BYTES = 64 * 1024
COLLECT_TIMEOUT_S = 2.0
STUCK_AFTER_S = 30.0


@dataclass(frozen=True)
class BodyProvider:

    key: str
    triggers: FrozenSet[str]
    read: Callable[[], Awaitable[Optional[Any]]]


_providers: Dict[str, BodyProvider] = {}
_skip: set = set()
_running: Dict[str, "tuple[asyncio.Task, float]"] = {}


def skip_next(key: str) -> None:
    _skip.add(key)


def register(key: str, triggers: List[str], read: Callable[[], Awaitable[Optional[Any]]]) -> Callable[[], None]:
    provider = BodyProvider(key, frozenset(triggers), read)
    _providers[key] = provider
    return lambda: _providers.pop(key, None) if _providers.get(key) is provider else None


def trigger_topics() -> FrozenSet[str]:
    return frozenset().union(*(p.triggers for p in _providers.values())) if _providers else frozenset()


def matching(named: List[str]) -> List[BodyProvider]:
    fams = {family_of(t) for t in named}
    return [p for p in _providers.values() if p.triggers & fams]


async def _one(provider: BodyProvider) -> Optional[Any]:
    try:
        body = await provider.read()
        if body is None:
            return None
        if len(json.dumps(body, separators=(",", ":"), allow_nan=False)) > MAX_BODY_BYTES:
            logger.info("resource_body_too_large", key=provider.key)
            return None
        return body
    except Exception as exc:  # noqa: BLE001
        logger.warning("resource_body_failed", key=provider.key, error_type=type(exc).__name__)
        return None


async def collect(providers: List[BodyProvider]) -> Dict[str, Any]:
    skipped = {p.key for p in providers if p.key in _skip}
    _skip.difference_update(skipped)
    now = time.monotonic()
    tasks: Dict[str, "asyncio.Task[Optional[Any]]"] = {}
    for p in providers:
        if p.key in skipped:
            continue
        busy = _running.get(p.key)
        if busy is not None and not busy[0].done():
            if now - busy[1] < STUCK_AFTER_S:
                continue
            busy[0].cancel()
        task = asyncio.ensure_future(_one(p))
        _running[p.key] = (task, now)
        tasks[p.key] = task
    if not tasks:
        return {}
    await asyncio.wait(tasks.values(), timeout=COLLECT_TIMEOUT_S)
    return {key: task.result() for key, task in tasks.items() if task.done() and not task.cancelled() and task.result() is not None}


from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

import structlog

from src.cplugs.huddle import service, sends, sending, triggers
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

QUIET_SETTING, CAP_SETTING = "sendQuietSeconds", "sendCapSeconds"
DEFAULT_QUIET_S, MIN_QUIET_S, MAX_QUIET_S = 10.0, 1.0, 300.0
DEFAULT_CAP_S, MIN_CAP_S, MAX_CAP_S = 45.0, 5.0, 600.0
MIN_SLEEP_S = 0.05
TOPIC = "sendq"
RETIRED_TOPIC = "tellq"
QUEUED = "queued"
NOTHING = "nothing"

FLUSH_ERRORS = (OSError, RuntimeError, ValueError, LookupError, AttributeError)


def _number(value: Any, low: float, high: float, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return min(max(float(value), low), high)


def window(settings: Dict[str, Any]) -> Tuple[float, float]:
    quiet = _number(settings.get(QUIET_SETTING), MIN_QUIET_S, MAX_QUIET_S, DEFAULT_QUIET_S)
    cap = _number(settings.get(CAP_SETTING), MIN_CAP_S, MAX_CAP_S, DEFAULT_CAP_S)
    return quiet, max(cap, quiet)


@dataclass
class Pending:

    key: str
    count: int
    first_at: float
    last_at: float

    def due_at(self, quiet: float, cap: float) -> float:
        return min(self.last_at + quiet, self.first_at + cap)


class SendQueue:

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._pending: Dict[str, Pending] = {}

    def now(self) -> float:
        return self._clock()

    def note(self, key: str) -> Pending:
        now = self._clock()
        found = self._pending.get(key)
        if found is None:
            found = self._pending[key] = Pending(key, 0, now, now)
        found.count += 1
        found.last_at = now
        return found

    def drop(self, key: str) -> Optional[Pending]:
        return self._pending.pop(key, None)

    def clear(self) -> None:
        self._pending.clear()

    def keys(self) -> List[str]:
        return [p.key for p in sorted(self._pending.values(), key=lambda p: p.first_at)]

    def due(self, quiet: float, cap: float) -> List[str]:
        now = self._clock()
        return [k for k in self.keys() if self._pending[k].due_at(quiet, cap) <= now]

    def next_due(self, quiet: float, cap: float) -> Optional[float]:
        return min((p.due_at(quiet, cap) for p in self._pending.values()), default=None)

    def snapshot(self, quiet: float, cap: float, only: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        keep = set(only) if only is not None else None
        rows = [p for p in self._pending.values() if keep is None or p.key in keep]
        return {
            "now": self._clock(), "quiet_s": quiet, "cap_s": cap,
            "count": sum(p.count for p in rows),
            "first_at": min((p.first_at for p in rows), default=None),
            "reset_at": max((p.last_at for p in rows), default=None),
            "due_at": min((p.due_at(quiet, cap) for p in rows), default=None),
            "lists": {p.key: {"count": p.count, "first_at": p.first_at, "last_at": p.last_at, "due_at": p.due_at(quiet, cap)} for p in rows},
        }


_queue = SendQueue()
_timer: Optional["asyncio.Task[None]"] = None


async def _run(call: Callable[[], Any]) -> Any:
    return await asyncio.to_thread(call)


def state(ctx: CplugContext, only: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    quiet, cap = window(ctx.settings_now())
    return _queue.snapshot(quiet, cap, only)


def _push(ctx: CplugContext) -> None:
    try:
        ctx.notify(TOPIC)
        ctx.notify(RETIRED_TOPIC)
    except (RuntimeError, ValueError) as exc:
        logger.warning("task_manager_send_queue_notify_failed", error=str(exc))


def _arm(ctx: CplugContext) -> None:
    global _timer
    if _timer is not None:
        _timer.cancel()
        _timer = None
    quiet, cap = window(ctx.settings_now())
    due = _queue.next_due(quiet, cap)
    if due is None:
        return
    delay = max(due - _queue.now(), MIN_SLEEP_S)
    _timer = asyncio.get_running_loop().create_task(_wait(ctx, delay), name="huddle-send-queue")


async def _wait(ctx: CplugContext, delay: float) -> None:
    await asyncio.sleep(delay)
    await flush_due(ctx)
    _arm(ctx)


def is_queued(key: str) -> bool:
    return key in _queue.keys()


def _released() -> None:
    triggers.nudge()


def queue_change(ctx: CplugContext, key: str) -> Pending:
    pending = _queue.note(key)
    _push(ctx)
    _arm(ctx)
    return pending


async def queue_untold(ctx: CplugContext, keys: Iterable[str]) -> List[Dict[str, Any]]:
    lists = (await _run(service.store(ctx).summary)).get("lists", {})
    out: List[Dict[str, Any]] = []
    for key in keys:
        untold = bool(lists.get(key, {}).get("untold"))
        if untold:
            queue_change(ctx, key)
        out.append({"list": key, "status": QUEUED if untold else NOTHING})
    return out


FAILED = "failed"
QUEUE_ERRORS = (sqlite3.Error, OSError, RuntimeError, ValueError, LookupError)


async def queue_owner_write(ctx: CplugContext, item: Mapping[str, Any]) -> str:
    if not sends.sendable(item):
        return NOTHING
    try:
        return (await queue_untold(ctx, [item["list"]]))[0]["status"]
    except QUEUE_ERRORS as exc:
        logger.warning("task_manager_send_queue_owner_write_failed", list=item.get("list"), item=item.get("id"), error_type=type(exc).__name__, error=str(exc)[:200])
        return FAILED


async def flush_list(ctx: CplugContext, key: str) -> Optional[Dict[str, Any]]:
    if _queue.drop(key) is None:
        return None
    _push(ctx)
    _released()
    store = service.store(ctx)
    summary = await _run(store.summary)
    if not summary.get("lists", {}).get(key, {}).get("untold"):
        return {"list": key, "status": NOTHING}
    name = (await _run(lambda: service.project_names(ctx))).get(key)
    infos = await ctx.sessions.list()
    return await sending.send_one_of_many(ctx, _run, key, name, infos, None)


async def _flush_keys(ctx: CplugContext, keys: Iterable[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for key in keys:
        try:
            outcome = await flush_list(ctx, key)
        except FLUSH_ERRORS as exc:
            logger.error("task_manager_send_queue_flush_failed", list=key, error_type=type(exc).__name__, error=str(exc)[:200])
            continue
        if outcome is not None:
            results.append(outcome)
    return results


async def flush_due(ctx: CplugContext) -> List[Dict[str, Any]]:
    quiet, cap = window(ctx.settings_now())
    return await _flush_keys(ctx, _queue.due(quiet, cap))


async def flush_now(ctx: CplugContext, keys: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    queued = _queue.keys()
    wanted = queued if keys is None else [k for k in queued if k in set(keys)]
    results = await _flush_keys(ctx, wanted)
    _arm(ctx)
    return results


async def before_immediate(ctx: CplugContext, key: str, target: str) -> None:
    for other in [k for k in _queue.keys() if k != key]:
        rows = await service.candidate_rows(ctx, other)
        choice = await _run(lambda: service.send_choice(ctx, rows, other))
        if choice["default"] == target:
            await _flush_keys(ctx, [other])
    if _queue.drop(key) is not None:
        _push(ctx)
        _released()
    _arm(ctx)


async def rearm_untold(ctx: CplugContext) -> List[str]:
    try:
        summary = await _run(service.store(ctx).summary)
    except (OSError, sqlite3.Error, RuntimeError, ValueError, LookupError) as exc:
        logger.warning("task_manager_send_queue_rearm_failed", error_type=type(exc).__name__, error=str(exc)[:200])
        return []
    queued = set(_queue.keys())
    keys = sorted(k for k, row in summary.get("lists", {}).items() if row.get("untold") and k not in queued)
    for key in keys:
        _queue.note(key)
    if keys:
        _push(ctx)
        _arm(ctx)
        logger.info("task_manager_send_queue_rearmed", lists=keys)
    return keys


def reset() -> None:
    global _timer
    if _timer is not None:
        _timer.cancel()
        _timer = None
    _queue.clear()


def use_clock(clock: Callable[[], float]) -> None:
    global _queue
    reset()
    _queue = SendQueue(clock)


__all__ = ["QUEUED", "NOTHING", "SendQueue", "Pending", "window", "state", "queue_change", "queue_owner_write", "FAILED", "flush_list", "flush_due", "flush_now",
           "before_immediate", "rearm_untold", "reset", "use_clock"]

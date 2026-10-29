
from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.cplugs.huddle import held_rows, service
from src.cplugs.sdk import session_bring_up
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

BUSY_CODES = session_bring_up.BUSY_CODES
GONE_CODES = session_bring_up.GONE_CODES

HELD = "held"
EXPIRED = "expired"
GONE = "gone"
NOT_SENT = "not_sent"

SETTING = "heldSendMinutes"
DEFAULT_MINUTES = 30
POLL_S = 3.0
BACKOFF = 1.5
MAX_BACKOFF_FACTOR = 10
BOOT_GRACE_S = 60.0
EXPIRED_TOAST_TITLE = "huddle: a held send did not go out"

Deliver = Callable[[], Awaitable[Dict[str, Any]]]


@dataclass
class Hold:

    list: str
    target: str
    label: Optional[str]
    state: str
    code: Optional[str]
    reason: Optional[str]
    since: float
    deadline: Optional[float] = None
    task: Optional[asyncio.Task] = field(default=None, repr=False)
    params: Optional[Dict[str, Any]] = field(default=None, repr=False)
    grace_until: Optional[float] = field(default=None, repr=False)

    def wire(self) -> Dict[str, Any]:
        return {"list": self.list, "target": self.target, "label": self.label, "state": self.state, "code": self.code,
                "reason": self.reason, "since": self.since, "deadline": self.deadline}


_holds: Dict[str, Hold] = {}


def snapshot() -> List[Dict[str, Any]]:
    return [h.wire() for h in sorted(_holds.values(), key=lambda h: h.since)]


def is_held(key: str) -> bool:
    entry = _holds.get(key)
    return entry is not None and entry.state == HELD


def minutes(ctx: CplugContext) -> float:
    value = ctx.settings.get(SETTING, DEFAULT_MINUTES)
    return float(value) if isinstance(value, (int, float)) and value >= 1 else float(DEFAULT_MINUTES)


def _push(ctx: CplugContext) -> None:
    try:
        ctx.notify("held")
    except (RuntimeError, ValueError) as exc:
        logger.warning("task_manager_held_notify_failed", error=str(exc))


def _store_row(ctx: CplugContext, entry: Hold) -> None:
    try:
        held_rows.save(service.store(ctx), {**entry.wire(), "params": entry.params})
    except (OSError, sqlite3.Error) as exc:
        logger.warning("task_manager_held_store_failed", list=entry.list, error_type=type(exc).__name__, error=str(exc)[:200])


def _unstore_row(ctx: CplugContext, key: str) -> None:
    try:
        held_rows.remove(service.store(ctx), key)
    except (OSError, sqlite3.Error) as exc:
        logger.warning("task_manager_held_unstore_failed", list=key, error_type=type(exc).__name__, error=str(exc)[:200])


def _drop(key: str, ctx: Optional[CplugContext] = None) -> Optional[Hold]:
    old = _holds.pop(key, None)
    if old is not None and old.task is not None:
        try:
            calling = asyncio.current_task()
        except RuntimeError:
            calling = None
        if old.task is not calling:
            old.task.cancel()
    if old is not None and old.params is not None and ctx is not None:
        _unstore_row(ctx, key)
    return old


def clear(ctx: CplugContext, key: str) -> bool:
    if _drop(key, ctx) is None:
        return False
    _push(ctx)
    return True


def record(ctx: CplugContext, key: str, target: str, label: Optional[str], exc: HTTPException) -> str:
    code = refusal_code(exc)
    state = GONE if code in GONE_CODES else NOT_SENT
    _drop(key, ctx)
    _holds[key] = Hold(key, target, label, state, code, refusal_reason(exc), time.time())
    _push(ctx)
    return state


def hold(ctx: CplugContext, key: str, target: str, label: Optional[str], exc: HTTPException, deliver: Deliver, *,
         params: Optional[Dict[str, Any]] = None, since: Optional[float] = None, deadline: Optional[float] = None,
         grace_until: Optional[float] = None) -> Dict[str, Any]:
    _drop(key, ctx)
    now = time.time()
    entry = Hold(key, target, label, HELD, refusal_code(exc), refusal_reason(exc), now if since is None else since,
                 now + minutes(ctx) * 60 if deadline is None else deadline, params=params, grace_until=grace_until)
    _holds[key] = entry
    if params is not None:
        _store_row(ctx, entry)
    entry.task = asyncio.get_running_loop().create_task(_watch(ctx, entry, deliver))
    logger.info("task_manager_send_held", list=key, target=target, code=entry.code, resumed=since is not None,
                minutes=round((entry.deadline - now) / 60, 2))
    _push(ctx)
    return entry.wire()


async def _watch(ctx: CplugContext, entry: Hold, deliver: Deliver) -> None:
    session_bring_up.QUIET_REFUSALS.set(True)
    delay, attempts = POLL_S, 0
    while _holds.get(entry.list) is entry:
        await asyncio.sleep(delay)
        if _holds.get(entry.list) is not entry:
            return
        if entry.deadline is not None and time.time() >= entry.deadline:
            _expire(ctx, entry, attempts)
            return
        attempts += 1
        try:
            await deliver()
        except HTTPException as exc:
            code = refusal_code(exc)
            if code in BUSY_CODES or (code in GONE_CODES and entry.grace_until is not None and time.time() < entry.grace_until):
                delay = min(delay * BACKOFF, POLL_S * MAX_BACKOFF_FACTOR)
                continue
            entry.task = None
            logger.info("task_manager_held_send_failed", list=entry.list, target=entry.target, code=code, attempts=attempts)
            record(ctx, entry.list, entry.target, entry.label, exc)
            return
        _drop_sent(ctx, entry)
        logger.info("task_manager_held_send_sent", list=entry.list, target=entry.target, attempts=attempts)
        _push(ctx)
        return


def _drop_sent(ctx: CplugContext, entry: Hold) -> None:
    _holds.pop(entry.list, None)
    if entry.params is not None:
        _unstore_row(ctx, entry.list)


def _expire(ctx: CplugContext, entry: Hold, attempts: int = 0) -> None:
    entry.state, entry.task = EXPIRED, None
    if entry.params is not None:
        _unstore_row(ctx, entry.list)
    logger.info("task_manager_held_send_expired", list=entry.list, target=entry.target, attempts=attempts)
    try:
        ctx.toast(entry.target, EXPIRED_TOAST_TITLE)
    except AttributeError as exc:
        logger.warning("task_manager_held_toast_unavailable", error=str(exc))
    _push(ctx)


def restore_expired(ctx: CplugContext, row: Dict[str, Any]) -> None:
    key = row["list"]
    entry = Hold(key, row["target"], row["label"], EXPIRED, row["code"], row["reason"], row["since"], row["deadline"], params=row["params"])
    _holds[key] = entry
    _expire(ctx, entry)


def refusal_code(exc: HTTPException) -> str:
    detail = exc.detail
    return str(detail.get("code") or "refused") if isinstance(detail, dict) else "refused"


def refusal_reason(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return str(detail.get("detail") or detail.get("message") or refusal_code(exc))
    return str(detail or "refused")


def reset() -> None:
    for key in list(_holds):
        _drop(key)

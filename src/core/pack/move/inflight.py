
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional

import structlog

logger = structlog.get_logger()

LOCK_REASONS = {
    "wake": "the other computer is already starting the agent, so it can no longer be stopped",
    "project": "the project is being copied there right now and that step cannot be stopped",
    "flip": "the other computer is already taking over the project, so it can no longer be stopped",
}


@dataclass
class Entry:

    task: "asyncio.Task[object]"
    subjects: tuple
    lock: Optional[str] = None


_running: Dict[str, Entry] = {}


def register(op_id: str, task: "asyncio.Task[object]", subjects: tuple) -> None:
    _running[op_id] = Entry(task, tuple(subjects))
    task.add_done_callback(lambda _t, key=op_id: _running.pop(key, None))


def lock(op_id: str, name: str) -> None:
    entry = _running.get(op_id)
    if entry is not None:
        entry.lock = name


def unlock(op_id: str, name: str) -> None:
    entry = _running.get(op_id)
    if entry is not None and entry.lock == name:
        entry.lock = None


def running(op_id: str) -> bool:
    return op_id in _running


def op_for(subject: str) -> Optional[str]:
    for op_id, entry in _running.items():
        if subject in entry.subjects:
            return op_id
    return None


def blocked_reason(op_id: str) -> Optional[str]:
    entry = _running.get(op_id)
    return LOCK_REASONS.get(entry.lock or "", None) if entry is not None and entry.lock else None


def cancel(op_id: str) -> str:
    entry = _running.get(op_id)
    if entry is None:
        return "not_running"
    if entry.lock:
        return "locked"
    entry.task.cancel()
    logger.info("pack_op_cancel_requested", op_id=op_id)
    return "cancelled"

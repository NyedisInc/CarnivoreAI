
from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from typing import Dict, Iterator, Optional, Set

import structlog

logger = structlog.get_logger()

_IN_FLIGHT: Dict[str, Optional[int]] = {}
_ENDED: Dict[str, float] = {}
HISTORY_SECONDS = 120.0


def _current_task_id() -> Optional[int]:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        return None
    return id(task) if task is not None else None


class RestartInFlightError(RuntimeError):

    def __init__(self, session_uuid: str) -> None:
        super().__init__(
            f"a restart of session {session_uuid} is already in progress"
        )
        self.session_uuid = session_uuid


@contextmanager
def claim(session_uuid: str) -> Iterator[None]:
    key = (session_uuid or "").strip()
    if not key:
        yield
        return
    owner = _current_task_id()
    if key in _IN_FLIGHT:
        if owner is not None and _IN_FLIGHT[key] == owner:
            yield
            return
        logger.warning("restart_refused_in_flight", session_uuid=key)
        raise RestartInFlightError(key)
    _IN_FLIGHT[key] = owner
    try:
        yield
    finally:
        _IN_FLIGHT.pop(key, None)
        now = time.monotonic()
        _ENDED[key] = now
        for stale in [k for k, t in list(_ENDED.items()) if now - t > HISTORY_SECONDS]:
            _ENDED.pop(stale, None)


IN_PROGRESS_CODE = "restart_in_progress"


def in_flight(session_uuid: str) -> bool:
    return (session_uuid or "").strip() in _IN_FLIGHT


def touched_since(t0: float) -> Set[str]:
    return set(dict(_IN_FLIGHT)) | {k for k, ended in dict(_ENDED).items() if ended >= t0}

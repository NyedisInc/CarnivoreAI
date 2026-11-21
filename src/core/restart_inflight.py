
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Dict, Iterator, Optional

import structlog

logger = structlog.get_logger()

_IN_FLIGHT: Dict[str, Optional[int]] = {}


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


IN_PROGRESS_CODE = "restart_in_progress"


def in_flight(session_uuid: str) -> bool:
    return (session_uuid or "").strip() in _IN_FLIGHT


from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Set

import structlog

logger = structlog.get_logger()

_IN_FLIGHT: Set[str] = set()


class RestartInFlightError(RuntimeError):
    """A restart for this stored session is already running.

    Description: raised by :func:`claim` when the key is held. Routes turn
      it into a 409; it is never a server fault.
    Inputs (constructor): session_uuid (str) - the contested row.
    Output: a RestartInFlightError whose ``session_uuid`` names the row.
    """

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
    if key in _IN_FLIGHT:
        logger.warning("restart_refused_in_flight", session_uuid=key)
        raise RestartInFlightError(key)
    _IN_FLIGHT.add(key)
    try:
        yield
    finally:
        _IN_FLIGHT.discard(key)


IN_PROGRESS_CODE = "restart_in_progress"


def http_detail(exc: RestartInFlightError) -> dict:
    return {"code": IN_PROGRESS_CODE, "message": str(exc)}


def in_flight(session_uuid: str) -> bool:
    return (session_uuid or "").strip() in _IN_FLIGHT

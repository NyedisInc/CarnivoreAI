
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()

BOOT_AT: float = time.time()


@dataclass
class Beat:

    busy_at: Optional[float] = None
    stop_seen_at: Optional[float] = None
    stopped: bool = False
    dialog: bool = False
    stale: bool = False
    cycle: int = 0


_beats: Dict[int, Beat] = {}


def reset() -> None:
    _beats.clear()


def beat(agent_id: int) -> Optional[Beat]:
    return _beats.get(agent_id)


def stop(agent_id: int, at: float) -> None:
    current = _beats.setdefault(agent_id, Beat())
    current.stop_seen_at = max(at, current.stop_seen_at or 0.0)


def observe(agent_id: int, observation: Any) -> None:
    from src.core.attention import evidence as ev  # noqa: PLC0415

    try:
        state, reason = observation.verdict.state, observation.verdict.reason
        dialog = observation.evidence.dialog is not None
        stale, cycle = bool(observation.stale), int(observation.cycle)
        seen_at = observation.observed_at.timestamp()
    except (AttributeError, TypeError, ValueError, OSError, OverflowError) as exc:
        logger.warning("swarm_lease_observe_unreadable", agent_id=agent_id, error_type=type(exc).__name__)
        return
    current = _beats.setdefault(agent_id, Beat())
    current.stale, current.cycle = stale, cycle
    if stale:
        return
    stops = (state == ev.STATE_NEEDS_USER and reason in (ev.REASON_QUESTION, ev.REASON_PERMISSION, ev.REASON_PLAN_APPROVAL, ev.REASON_INPUT)) or dialog
    current.stopped, current.dialog = stops, dialog
    if stops:
        current.stop_seen_at = seen_at
    if state == ev.STATE_BUSY:
        current.busy_at = seen_at

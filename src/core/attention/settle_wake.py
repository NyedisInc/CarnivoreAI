from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from src.core.attention.evidence import STATE_DONE_IDLE
from src.core.attention.resolve_rest import DONE_QUIET_SECONDS

if TYPE_CHECKING:
    from src.core.attention.watcher import Observation

SETTLE_MARGIN_SECONDS: float = 0.1


def settle_delay(observation: Optional["Observation"]) -> Optional[float]:
    if observation is None or observation.verdict.state == STATE_DONE_IDLE:
        return None
    evidence = observation.evidence
    if evidence.codex is not None:
        return None
    appended = getattr(evidence.transcript, "newest_append_at", None)
    if appended is None:
        return None
    try:
        quiet = (evidence.now - appended).total_seconds()
    except TypeError:
        return None
    if 0 <= quiet < DONE_QUIET_SECONDS:
        return DONE_QUIET_SECONDS - quiet + SETTLE_MARGIN_SECONDS
    return None

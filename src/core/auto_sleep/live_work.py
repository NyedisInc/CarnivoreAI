"""What a session still has running or scheduled, so auto-sleep never ends it.

PURE: this module reads an :class:`~src.core.attention.evidence.Evidence`
bundle and answers :class:`SleepHold` or None. It opens nothing. Two callers:

* the listing stamp (``src/api/sleep_hold_listing.py``) judges the watcher's
  cached observation, ``require_measured=False``: a field the reader did not
  fill is simply not a reason there;
* the auto-sleep pass (``sleeper.py``) judges a FRESH read taken right before
  it acts, ``require_measured=True``: a claude whose timers, subagents or
  process tree could not be measured is kept awake, because unknown is never
  idle (fail safe). Codex records none of these and is never held here.

Neither the coffee cup nor a pin changes the answer: the hold applies to every
session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional, Tuple

from src.core.attention.evidence import FAMILY_CODEX
from src.core.background_work.measured import STATE_RUNNING, STATE_UNKNOWN

REASON_TIMERS = "timers"
REASON_SUBAGENTS = "subagents"
REASON_BACKGROUND = "background"
REASON_PARKED = "parked"
REASON_UNMEASURED = "unmeasured"

ALL_REASONS = (REASON_TIMERS, REASON_SUBAGENTS, REASON_BACKGROUND, REASON_PARKED, REASON_UNMEASURED)

_STATE_OK = "ok"
_STATE_UNCHECKED = "unchecked"


@dataclass(frozen=True)
class SleepHold:

    reasons: Tuple[str, ...]
    text: str
    timers_live: Optional[int] = None
    next_fire_at: Optional[datetime] = None
    subagents_running: Optional[int] = None
    background_count: Optional[int] = None


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _clock(value: datetime) -> str:
    return value.astimezone().strftime("%H:%M")


def _timer_part(evidence: Any, require_measured: bool, found: dict) -> Optional[str]:
    tally = getattr(evidence, "timers", None)
    if tally is None or getattr(tally, "state", None) == _STATE_UNCHECKED:
        found["unmeasured"] = found["unmeasured"] or tally is not None or require_measured
        return None
    live = getattr(tally, "live", None) or 0
    if getattr(tally, "state", None) != _STATE_OK or live <= 0:
        return None
    found["reasons"].append(REASON_TIMERS)
    found["timers_live"] = live
    found["next_fire_at"] = getattr(tally, "next_fire_at", None)
    text = _plural(live, "live timer")
    return text + (f", next {_clock(found['next_fire_at'])}" if found["next_fire_at"] else "")


def _subagent_part(evidence: Any, require_measured: bool, found: dict) -> Optional[str]:
    tally = getattr(evidence, "subagents", None)
    if tally is None or getattr(tally, "state", None) == _STATE_UNCHECKED:
        found["unmeasured"] = found["unmeasured"] or tally is not None or require_measured
        return None
    running = getattr(tally, "running", None) or 0
    if running <= 0:
        return None
    found["reasons"].append(REASON_SUBAGENTS)
    found["subagents_running"] = running
    return _plural(running, "subagent") + " running"


def _background_part(evidence: Any, require_measured: bool, found: dict) -> Optional[str]:
    measure = getattr(evidence, "background_process", None)
    opened = getattr(evidence, "background_open", None) or 0
    if measure is None:
        found["unmeasured"] = found["unmeasured"] or require_measured
    elif measure.state == STATE_UNKNOWN:
        found["unmeasured"] = True
    running = measure is not None and measure.state == STATE_RUNNING
    count = max(opened, (measure.count or 1) if running else 0)
    if count <= 0:
        return None
    found["reasons"].append(REASON_BACKGROUND)
    found["background_count"] = count
    return "background shell running" if count == 1 else f"{count} background shells running"


def _parked_part(evidence: Any, found: dict) -> Optional[str]:
    parked = getattr(evidence, "parked_work", None)
    if parked is None:
        return None
    if getattr(parked, "is_unmeasured", False):
        found["unmeasured"] = True
        return None
    if getattr(parked, "is_live", False):
        found["reasons"].append(REASON_PARKED)
        return "a subagent's background work is running"
    return None


def hold_for(evidence: Any, *, require_measured: bool) -> Optional[SleepHold]:
    if evidence is None or getattr(evidence, "agent_family", None) == FAMILY_CODEX:
        return None
    found = {"reasons": [], "unmeasured": False, "timers_live": None, "next_fire_at": None,
             "subagents_running": None, "background_count": None}
    parts: List[str] = [part for part in (
        _timer_part(evidence, require_measured, found),
        _subagent_part(evidence, require_measured, found),
        _background_part(evidence, require_measured, found),
        _parked_part(evidence, found),
    ) if part]
    if found["unmeasured"]:
        found["reasons"].append(REASON_UNMEASURED)
        parts.append("could not measure its timers or background work")
    if not found["reasons"]:
        return None
    return SleepHold(
        reasons=tuple(found["reasons"]), text="kept awake: " + "; ".join(parts),
        timers_live=found["timers_live"], next_fire_at=found["next_fire_at"],
        subagents_running=found["subagents_running"], background_count=found["background_count"],
    )


__all__ = ["SleepHold", "hold_for", "ALL_REASONS", "REASON_TIMERS", "REASON_SUBAGENTS",
           "REASON_BACKGROUND", "REASON_PARKED", "REASON_UNMEASURED"]

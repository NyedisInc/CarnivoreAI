
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

CLAUDE_FLOOR_SECONDS = 180.0

CODEX_FLOOR_SECONDS = 60.0

JITTER_FRACTION = 0.1

RATE_LIMITED_FLOOR_SECONDS = 360.0

RATE_LIMITED_GROWTH = 1.5

RATE_LIMITED_MAX_SECONDS = 1800.0

TICK_SECONDS = 5.0

CREDENTIAL_RECHECK_SECONDS = 15.0

_CREDENTIAL_ONLY_RECHECK_STATES = frozenset({"missing", "expired", "refused"})

_FLOORS = {
    "claude": CLAUDE_FLOOR_SECONDS,
    "codex": CODEX_FLOOR_SECONDS,
}


def floor_seconds(provider: str) -> float:
    return _FLOORS.get(provider, CLAUDE_FLOOR_SECONDS)


def apply_jitter(seconds: float, random_unit: float) -> float:
    return seconds * (1.0 + JITTER_FRACTION * (2.0 * random_unit - 1.0))


def next_interval_seconds(
    *,
    provider: str,
    state: str,
    retry_after_seconds: Optional[float] = None,
    rate_limited_interval_seconds: Optional[float] = None,
    random_unit: float = 0.5,
    request_skipped: bool = False,
) -> float:
    if request_skipped and state in _CREDENTIAL_ONLY_RECHECK_STATES:
        return CREDENTIAL_RECHECK_SECONDS
    if state != "rate_limited":
        return apply_jitter(floor_seconds(provider), random_unit)

    stated = (
        retry_after_seconds
        if retry_after_seconds is not None and retry_after_seconds > 0
        else None
    )
    if rate_limited_interval_seconds is None:
        backoff = stated if stated is not None else RATE_LIMITED_FLOOR_SECONDS
        return backoff
    grown = min(
        rate_limited_interval_seconds * RATE_LIMITED_GROWTH,
        RATE_LIMITED_MAX_SECONDS,
    )
    if stated is not None and stated > grown:
        return stated
    return grown


def next_poll_at(now: datetime, interval_seconds: float) -> datetime:
    return now + timedelta(seconds=interval_seconds)

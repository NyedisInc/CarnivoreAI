
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

FORCE_REFRESH_FLOOR_SECONDS: float = 10.0

SCHEDULED_REFRESH_SECONDS: float = 6 * 60 * 60.0

STALE_AFTER_SECONDS: float = 2 * SCHEDULED_REFRESH_SECONDS


def is_degraded(
    as_of: Optional[datetime], *, now: datetime, staleness_days: int
) -> bool:
    if as_of is None:
        return False
    return now - as_of > timedelta(days=staleness_days)


def within_force_floor(
    fetched_monotonic: Optional[float], *, monotonic_now: float
) -> bool:
    if fetched_monotonic is None:
        return False
    return monotonic_now - fetched_monotonic < FORCE_REFRESH_FLOOR_SECONDS


def is_overdue(fetched_monotonic: Optional[float], *, monotonic_now: float) -> bool:
    if fetched_monotonic is None:
        return True
    return monotonic_now - fetched_monotonic >= STALE_AFTER_SECONDS

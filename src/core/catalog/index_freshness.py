
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

FORCE_REFRESH_FLOOR_SECONDS: float = 10.0

SCHEDULED_REFRESH_SECONDS: float = 6 * 60 * 60.0

STALE_AFTER_SECONDS: float = 2 * SCHEDULED_REFRESH_SECONDS


def is_degraded(
    as_of: Optional[datetime], *, now: datetime, staleness_days: int
) -> bool:
    """Whether a held index is older than the trust root allows.

    Description: the SAME comparison
      :func:`~src.core.catalog.verify.verify_index` makes, against the
      same window, but taken at whatever instant the caller passes rather
      than at the moment the bytes last changed. NO INDEX HELD IS NOT
      DEGRADED: there is nothing to be stale about, and the empty
      snapshot already says so through a null serial. An ``as_of`` in the
      future is not degraded either, which matches the verifier: a clock
      disagreement is not staleness.
    Inputs: as_of (datetime | None) - the index's own ``generated_at``,
      timezone aware. now (datetime) - the present instant, timezone
      aware, from the caller's Clock port. staleness_days (int) - the
      trust root's window. Keyword only except the first.
    Output: bool.
    Example: is_degraded(built, now=today, staleness_days=30) -> True
    """
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

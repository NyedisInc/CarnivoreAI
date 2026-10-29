
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Mapping, Optional, Sequence

from src.core.project_history.classify import STATE_ASLEEP, STATE_RUNNING, parse_stamp, row_state

ACTIVITY_DAYS = 14

_INSTANT_COLUMNS = ("created_at", "last_work_at", "last_seen_running_at")

KIND_AUTOMATED = "automated"


def is_automated(row: Mapping[str, Any]) -> bool:
    return row.get("kind") == KIND_AUTOMATED


def activity_days(rows: Sequence[Mapping[str, Any]], now: Optional[datetime] = None) -> List[int]:
    today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    first = today - timedelta(days=ACTIVITY_DAYS - 1)
    counts = [0] * ACTIVITY_DAYS
    for row in rows:
        days = _days_of(row, first, today)
        for day in days:
            counts[(day - first).days] += 1
    return counts


def _days_of(row: Mapping[str, Any], first: date, today: date) -> set:
    days = set()
    for column in _INSTANT_COLUMNS:
        stamp = parse_stamp(row.get(column))
        if stamp is not None and first <= stamp.date() <= today:
            days.add(stamp.date())
    if row_state(row) in (STATE_RUNNING, STATE_ASLEEP):
        starts = [parse_stamp(row.get(c)) for c in _INSTANT_COLUMNS]
        known = [s.date() for s in starts if s is not None]
        begin = max(min(known) if known else first, first)
        day = begin
        while day <= today:
            days.add(day)
            day += timedelta(days=1)
    return days

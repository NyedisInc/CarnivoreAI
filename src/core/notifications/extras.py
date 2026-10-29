
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from src.core.notifications import types
from src.core.notifications.routing_view import QuietHours

AWAY_HOLD_SECONDS = 120.0
DEFAULT_REMINDER_MINUTES = 10


def parse_hhmm(value: str) -> Optional[int]:
    try:
        hours, minutes = value.split(":")
        h, m = int(hours), int(minutes)
    except (ValueError, AttributeError):
        return None
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def in_quiet_hours(quiet: Optional[QuietHours], now: datetime) -> bool:
    if quiet is None:
        return False
    start, end = parse_hhmm(quiet.start), parse_hhmm(quiet.end)
    if start is None or end is None or start == end:
        return False
    minute = now.hour * 60 + now.minute
    return start <= minute < end if start < end else (minute >= start or minute < end)


def passes_quiet_hours(type_id: str) -> bool:
    row = types.get_type(type_id)
    return bool(row is not None and row.defaults.passes_quiet_hours)


def project_allowed(projects: Sequence[str], project: str) -> bool:
    return not projects or not project or project in projects


def should_hold_for_away(away_on: bool, screen_active: bool) -> bool:
    return away_on and screen_active


def reminder_delay_seconds(type_id: str, minutes: Optional[int]) -> Optional[float]:
    if type_id not in types.NEEDS_YOU:
        return None
    value = DEFAULT_REMINDER_MINUTES if minutes is None else minutes
    return float(value * 60) if value > 0 else None

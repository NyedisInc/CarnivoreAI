
from __future__ import annotations

import calendar
import json
import math
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Dict, Mapping, Optional
from zoneinfo import ZoneInfo

from src.core.time_zone import app_time_zone
from src.cplugs.huddle.rules import TaskManagerInvalid

DAILY, WEEKLY, HOURLY, MONTHLY = "daily", "weekly", "hourly", "monthly"
FREQS = (DAILY, WEEKLY, HOURLY, MONTHLY)
FIELDS = ("freq", "interval", "byweekday", "time", "monthday")
MAX_HOURS = 168
SEARCH_DAYS = 400
_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_BAD = "repeat must be {freq: daily|weekly|hourly|monthly, time: 'HH:MM', byweekday?: [0-6], monthday?: 1-31, interval?: hours} or an empty string to stop repeating"


def _weekday(value: object) -> int:
    if isinstance(value, bool):
        raise TaskManagerInvalid(_BAD)
    if isinstance(value, int) and 0 <= value <= 6:
        return value
    if isinstance(value, str) and value.strip()[:3].lower() in _DAY_NAMES:
        return _DAY_NAMES.index(value.strip()[:3].lower())
    raise TaskManagerInvalid("byweekday holds weekdays 0 (monday) to 6 (sunday), or names like 'mon'")


def _clock(value: object) -> str:
    try:
        hour, minute = (int(part) for part in str(value).strip().split(":"))
        dtime(hour, minute)
    except ValueError as exc:
        raise TaskManagerInvalid("time must be a 24-hour 'HH:MM', e.g. '09:00'") from exc
    return f"{hour:02d}:{minute:02d}"


def parse_rule(value: object) -> Optional[Dict[str, Any]]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, Mapping):
        raise TaskManagerInvalid(_BAD)
    unknown = sorted(set(value) - set(FIELDS))
    if unknown:
        raise TaskManagerInvalid(f"repeat has no field {', '.join(unknown)}; it takes {', '.join(FIELDS)}")
    freq = value.get("freq")
    if freq not in FREQS:
        raise TaskManagerInvalid(_BAD)
    rule: Dict[str, Any] = {"freq": freq}
    interval = value.get("interval")
    if freq == HOURLY:
        if interval is None:
            interval = 1
        if isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= MAX_HOURS:
            raise TaskManagerInvalid(f"interval is a whole number of hours, 1 to {MAX_HOURS}")
        rule["interval"] = interval
        if value.get("time") is not None or value.get("byweekday") or value.get("monthday") is not None:
            raise TaskManagerInvalid("an every-n-hours repeat takes only interval (it counts from the schedule's own time)")
        return rule
    if interval not in (None, 1):
        raise TaskManagerInvalid("interval applies to an hourly repeat only")
    if value.get("time") is None:
        raise TaskManagerInvalid("time is required: 'HH:MM', 24-hour, in the app's time zone")
    rule["time"] = _clock(value["time"])
    if freq == WEEKLY:
        days = value.get("byweekday")
        if not isinstance(days, (list, tuple)) or not days:
            raise TaskManagerInvalid("a weekly repeat needs byweekday: the weekdays, 0 (monday) to 6 (sunday)")
        rule["byweekday"] = sorted({_weekday(d) for d in days})
    elif value.get("byweekday"):
        raise TaskManagerInvalid("byweekday applies to a weekly repeat only")
    if freq == MONTHLY:
        day = value.get("monthday")
        if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31:
            raise TaskManagerInvalid("a monthly repeat needs monthday, 1 to 31 (a shorter month fires on its last day)")
        rule["monthday"] = day
    elif value.get("monthday") is not None:
        raise TaskManagerInvalid("monthday applies to a monthly repeat only")
    return rule


def dumps(rule: Optional[Mapping[str, Any]]) -> Optional[str]:
    return None if rule is None else json.dumps(rule, sort_keys=True, separators=(",", ":"))


def loads(text: Optional[str]) -> Optional[Dict[str, Any]]:
    return None if not text else json.loads(text)


def _occurrence(day: date, rule: Mapping[str, Any], zone: ZoneInfo) -> Optional[float]:
    freq = rule["freq"]
    if freq == WEEKLY and day.weekday() not in rule["byweekday"]:
        return None
    if freq == MONTHLY and day.day != min(rule["monthday"], calendar.monthrange(day.year, day.month)[1]):
        return None
    hour, minute = (int(p) for p in rule["time"].split(":"))
    return datetime.combine(day, dtime(hour, minute), tzinfo=zone).timestamp()


def next_after(rule: Mapping[str, Any], after: float, anchor: Optional[float] = None) -> float:
    if rule["freq"] == HOURLY:
        step = rule["interval"] * 3600
        base = after if anchor is None else anchor
        if base > after:
            return base
        return base + (math.floor((after - base) / step) + 1) * step
    zone = app_time_zone.zone()
    first = datetime.fromtimestamp(after, zone).date()
    for offset in range(SEARCH_DAYS):
        stamp = _occurrence(first + timedelta(days=offset), rule, zone)
        if stamp is not None and stamp > after:
            return stamp
    raise TaskManagerInvalid("that repeat never comes due")

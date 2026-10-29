
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import FrozenSet, List, Optional, Sequence, Tuple

SEARCH_DAYS: int = 4 * 366 + 1

_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun",
           "jul", "aug", "sep", "oct", "nov", "dec")
_DAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")

_FIELDS: Tuple[Tuple[int, int, Sequence[str], int], ...] = (
    (0, 59, (), 0),
    (0, 23, (), 0),
    (1, 31, (), 0),
    (1, 12, _MONTHS, 1),
    (0, 7, _DAYS, 0),
)


class CronParseError(ValueError):
    pass


@dataclass(frozen=True)
class CronSchedule:

    minutes: FrozenSet[int]
    hours: FrozenSet[int]
    days: FrozenSet[int]
    months: FrozenSet[int]
    weekdays: FrozenSet[int]
    dom_any: bool
    dow_any: bool
    nth_weekdays: FrozenSet[Tuple[int, int]] = frozenset()

    def day_matches(self, day: datetime) -> bool:
        if day.month not in self.months:
            return False
        weekday = (day.weekday() + 1) % 7
        dom_ok = day.day in self.days
        dow_ok = weekday in self.weekdays or (weekday, (day.day - 1) // 7 + 1) in self.nth_weekdays
        if self.dom_any and self.dow_any:
            return True
        if self.dom_any:
            return dow_ok
        if self.dow_any:
            return dom_ok
        return dom_ok or dow_ok


def _value(token: str, low: int, high: int, names: Sequence[str], offset: int) -> int:
    lowered = token.lower()
    if names and lowered in names:
        return names.index(lowered) + offset
    if not token.isdigit():
        raise CronParseError(f"not a number: {token!r}")
    number = int(token)
    if number < low or number > high:
        raise CronParseError(f"{number} outside {low}-{high}")
    return number


def _field(text: str, low: int, high: int, names: Sequence[str], offset: int) -> FrozenSet[int]:
    allowed: set = set()
    for part in text.split(","):
        if not part:
            raise CronParseError("empty list item")
        base, _, step_text = part.partition("/")
        step = 1
        if step_text:
            if not step_text.isdigit() or int(step_text) == 0:
                raise CronParseError(f"bad step: {step_text!r}")
            step = int(step_text)
        if base == "*":
            start, end = low, high
        elif "-" in base:
            left, _, right = base.partition("-")
            start = _value(left, low, high, names, offset)
            end = _value(right, low, high, names, offset)
            if end < start:
                raise CronParseError(f"reversed range: {base!r}")
        else:
            start = _value(base, low, high, names, offset)
            end = high if step_text else start
        allowed.update(range(start, end + 1, step))
    return frozenset(allowed)


def _split_nth(text: str) -> Tuple[FrozenSet[Tuple[int, int]], str]:
    nth: set = set()
    rest: List[str] = []
    for part in text.split(","):
        if "#" not in part:
            rest.append(part)
            continue
        day_text, _, count_text = part.partition("#")
        day = _value(day_text, *_FIELDS[4])
        if not count_text.isdigit() or not 1 <= int(count_text) <= 5:
            raise CronParseError(f"nth weekday must be 1-5: {part!r}")
        nth.add((0 if day == 7 else day, int(count_text)))
    return frozenset(nth), ",".join(rest)


def parse_cron(expression: str) -> CronSchedule:
    if not isinstance(expression, str):
        raise CronParseError("not a string")
    fields = expression.split()
    if len(fields) != 5:
        raise CronParseError(f"expected 5 fields, got {len(fields)}")
    nth, plain_dow = _split_nth(fields[4])
    parsed: List[FrozenSet[int]] = [
        _field(text, *spec) for text, spec in zip(fields[:4], _FIELDS)
    ]
    plain = _field(plain_dow, *_FIELDS[4]) if plain_dow else frozenset()
    weekdays = frozenset(0 if day == 7 else day for day in plain)
    return CronSchedule(
        minutes=parsed[0], hours=parsed[1], days=parsed[2], months=parsed[3],
        weekdays=weekdays, dom_any=fields[2] == "*", dow_any=fields[4] == "*", nth_weekdays=nth,
    )


def next_fire(schedule: CronSchedule, after: datetime) -> Optional[datetime]:
    local = after.astimezone()
    start = (local + timedelta(minutes=1)).replace(second=0, microsecond=0)
    hours = sorted(schedule.hours)
    minutes = sorted(schedule.minutes)
    day = start.replace(hour=0, minute=0)
    for offset in range(SEARCH_DAYS):
        current = (day + timedelta(days=offset)).replace(tzinfo=None)
        if not schedule.day_matches(current):
            continue
        for hour in hours:
            for minute in minutes:
                candidate = current.replace(hour=hour, minute=minute).astimezone()
                if candidate >= start:
                    return candidate.astimezone(timezone.utc)
    return None


def next_fire_text(expression: str, after: datetime) -> Optional[datetime]:
    try:
        return next_fire(parse_cron(expression), after)
    except CronParseError:
        return None

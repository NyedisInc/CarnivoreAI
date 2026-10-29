
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.core.automations.models import MIN_INTERVAL_S, AutomationInvalid
from src.core.timers.cron import CronParseError, CronSchedule, next_fire, parse_cron

FLOOR_DAYS = 8
FLOOR_FIRES = 800


def next_epoch(schedule: CronSchedule, after: float) -> Optional[float]:
    found = next_fire(schedule, datetime.fromtimestamp(after, tz=timezone.utc))
    return found.timestamp() if found is not None else None


def compile_cron(expression: str, now: float) -> CronSchedule:
    try:
        schedule = parse_cron(expression)
    except CronParseError as exc:
        raise AutomationInvalid("cron_invalid", str(exc)) from exc
    previous = next_epoch(schedule, now)
    if previous is None:
        raise AutomationInvalid("never_fires", "no fire inside the search window")
    horizon = now + FLOOR_DAYS * 86400
    for _ in range(FLOOR_FIRES):
        following = next_epoch(schedule, previous)
        if following is None or following > horizon:
            break
        if following - previous < MIN_INTERVAL_S:
            raise AutomationInvalid("interval_under_15_min", "two fires are closer than 15 minutes")
        previous = following
    return schedule


from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.cplugs.huddle import recurrence
from src.cplugs.huddle.recurrence import next_after, parse_rule
from src.cplugs.huddle.rules import TaskManagerInvalid

HOUR = 3600.0
ZONE = ZoneInfo("America/New_York")


def ny(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> float:
    return datetime(year, month, day, hour, minute, tzinfo=ZONE).timestamp()


def at(stamp: float) -> tuple:
    moment = datetime.fromtimestamp(stamp, ZONE)
    return (moment.month, moment.day, moment.hour, moment.minute)


DAILY = {"freq": "daily", "time": "09:00"}


def test_daily_is_the_next_wall_time_and_strictly_after():
    assert at(next_after(DAILY, ny(2026, 10, 5, 8, 59))) == (10, 5, 9, 0)
    assert at(next_after(DAILY, ny(2026, 10, 5, 9, 0))) == (10, 6, 9, 0)
    assert at(next_after(DAILY, ny(2026, 10, 5, 23, 59))) == (10, 6, 9, 0)


def test_spring_forward_keeps_nine_am_and_the_gap_is_23_hours():
    first = next_after(DAILY, ny(2026, 3, 7, 10))
    assert at(first) == (3, 8, 9, 0)
    assert first - ny(2026, 3, 7, 9) == 23 * HOUR
    assert at(next_after(DAILY, first)) == (3, 9, 9, 0)


def test_fall_back_keeps_nine_am_and_the_gap_is_25_hours():
    first = next_after(DAILY, ny(2026, 10, 31, 10))
    assert at(first) == (11, 1, 9, 0)
    assert first - ny(2026, 10, 31, 9) == 25 * HOUR


def test_a_wall_time_inside_the_spring_gap_fires_at_the_instant_zoneinfo_maps_it_to():
    stamp = next_after({"freq": "daily", "time": "02:30"}, ny(2026, 3, 8, 0, 5))
    assert stamp > ny(2026, 3, 8, 0, 5) and at(stamp)[:2] == (3, 8)
    assert at(stamp)[2] in (1, 3)
    assert at(next_after({"freq": "daily", "time": "02:30"}, stamp)) == (3, 9, 2, 30)


def test_fall_back_repeated_hour_fires_on_its_first_pass_once():
    rule = {"freq": "daily", "time": "01:30"}
    first = next_after(rule, ny(2026, 10, 31, 12))
    assert at(first) == (11, 1, 1, 30)
    assert at(next_after(rule, first)) == (11, 2, 1, 30)


def test_weekdays_skip_the_weekend():
    rule = {"freq": "weekly", "byweekday": [0, 1, 2, 3, 4], "time": "09:00"}
    friday_noon = ny(2026, 10, 9, 12)
    assert at(next_after(rule, friday_noon)) == (10, 12, 9, 0)
    assert at(next_after(rule, ny(2026, 10, 12, 8))) == (10, 12, 9, 0)


def test_picked_weekdays_only():
    rule = {"freq": "weekly", "byweekday": [1, 3], "time": "18:15"}
    assert at(next_after(rule, ny(2026, 10, 5, 12))) == (10, 6, 18, 15)
    assert at(next_after(rule, ny(2026, 10, 6, 19))) == (10, 8, 18, 15)
    assert at(next_after(rule, ny(2026, 10, 8, 19))) == (10, 13, 18, 15)


@pytest.mark.parametrize("after,expected", [
    ((2026, 1, 20), (1, 31)),
    ((2026, 1, 31, 10), (2, 28)),
    ((2027, 12, 31, 10), (1, 31)),
    ((2028, 1, 31, 10), (2, 29)),
    ((2026, 3, 31, 10), (4, 30)),
    ((2026, 4, 30, 10), (5, 31)),
])
def test_monthly_on_the_31st_falls_back_to_the_last_day(after, expected):
    rule = {"freq": "monthly", "monthday": 31, "time": "09:00"}
    stamp = next_after(rule, ny(*after))
    assert at(stamp)[:2] == expected and at(stamp)[2:] == (9, 0)


def test_monthly_on_a_normal_day_and_the_same_day_before_the_time():
    rule = {"freq": "monthly", "monthday": 15, "time": "09:00"}
    assert at(next_after(rule, ny(2026, 10, 15, 8))) == (10, 15, 9, 0)
    assert at(next_after(rule, ny(2026, 10, 15, 9))) == (11, 15, 9, 0)
    assert at(next_after(rule, ny(2026, 12, 20))) == (1, 15, 9, 0)


def test_every_n_hours_counts_from_the_anchor_and_is_elapsed_time():
    rule = {"freq": "hourly", "interval": 4}
    anchor = ny(2026, 3, 8, 0)
    assert next_after(rule, anchor + 1, anchor) == anchor + 4 * HOUR
    assert next_after(rule, anchor + 4 * HOUR, anchor) == anchor + 8 * HOUR
    assert next_after(rule, anchor + 10 * HOUR + 5, anchor) == anchor + 12 * HOUR
    assert next_after(rule, anchor - 100, anchor) == anchor
    assert next_after(rule, anchor + 7 * 24 * HOUR + 1, anchor) == anchor + 7 * 24 * HOUR + 4 * HOUR
    assert next_after(rule, 1000.0) == 1000.0 + 4 * HOUR


def test_parse_normalizes_and_validates():
    assert parse_rule("") is None and parse_rule(None) is None and parse_rule("  ") is None
    assert parse_rule({"freq": "daily", "time": "9:05"}) == {"freq": "daily", "time": "09:05"}
    assert parse_rule({"freq": "weekly", "byweekday": ["Fri", 0, "monday", 0], "time": "07:00"}) == {"freq": "weekly", "byweekday": [0, 4], "time": "07:00"}
    assert parse_rule({"freq": "hourly"}) == {"freq": "hourly", "interval": 1}
    assert parse_rule({"freq": "hourly", "interval": 6}) == {"freq": "hourly", "interval": 6}
    assert parse_rule({"freq": "monthly", "monthday": 31, "time": "23:59"}) == {"freq": "monthly", "monthday": 31, "time": "23:59"}
    bad = [
        "daily", ["daily"], {"freq": "yearly", "time": "09:00"}, {"time": "09:00"},
        {"freq": "daily"}, {"freq": "daily", "time": "25:00"}, {"freq": "daily", "time": "nine"}, {"freq": "daily", "time": "09:00", "color": "red"},
        {"freq": "weekly", "time": "09:00"}, {"freq": "weekly", "byweekday": [], "time": "09:00"}, {"freq": "weekly", "byweekday": [7], "time": "09:00"},
        {"freq": "weekly", "byweekday": [True], "time": "09:00"}, {"freq": "daily", "byweekday": [1], "time": "09:00"},
        {"freq": "monthly", "time": "09:00"}, {"freq": "monthly", "monthday": 32, "time": "09:00"}, {"freq": "monthly", "monthday": 0, "time": "09:00"},
        {"freq": "hourly", "interval": 0}, {"freq": "hourly", "interval": 169}, {"freq": "hourly", "interval": 2.5}, {"freq": "hourly", "interval": 2, "time": "09:00"},
        {"freq": "daily", "interval": 3, "time": "09:00"}, {"freq": "daily", "monthday": 3, "time": "09:00"},
    ]
    for value in bad:
        with pytest.raises(TaskManagerInvalid):
            parse_rule(value)


def test_dumps_and_loads_round_trip():
    rule = parse_rule({"freq": "weekly", "byweekday": [4, 0], "time": "09:00"})
    assert recurrence.loads(recurrence.dumps(rule)) == rule
    assert recurrence.dumps(None) is None and recurrence.loads(None) is None and recurrence.loads("") is None

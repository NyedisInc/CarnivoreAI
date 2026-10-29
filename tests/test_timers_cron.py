
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.core.timers.cron import CronParseError, next_fire, next_fire_text, parse_cron


def _local(*parts: int) -> datetime:
    return datetime(*parts).astimezone()


def test_every_five_minutes_fires_on_the_next_multiple():
    fire = next_fire(parse_cron("*/5 * * * *"), _local(2026, 9, 27, 10, 7, 30))
    assert fire.astimezone() .replace(tzinfo=None) == datetime(2026, 9, 27, 10, 10)
    assert fire.tzinfo == timezone.utc


def test_a_fire_is_strictly_after_the_instant():
    fire = next_fire(parse_cron("10 * * * *"), _local(2026, 9, 27, 10, 10, 0))
    assert fire.astimezone().replace(tzinfo=None) == datetime(2026, 9, 27, 11, 10)


def test_a_one_shot_date_expression():
    fire = next_fire(parse_cron("54 12 17 8 *"), _local(2026, 8, 1, 0, 0))
    assert fire.astimezone().replace(tzinfo=None) == datetime(2026, 8, 17, 12, 54)


def test_names_ranges_steps_and_lists():
    schedule = parse_cron("0,30 9-17/4 * jan-mar mon")
    assert schedule.minutes == {0, 30}
    assert schedule.hours == {9, 13, 17}
    assert schedule.months == {1, 2, 3}
    assert schedule.weekdays == {1}


def test_sunday_is_both_zero_and_seven():
    assert parse_cron("0 0 * * 7").weekdays == {0}


def test_both_day_fields_restricted_match_either():
    schedule = parse_cron("0 9 1 * mon")
    assert schedule.day_matches(datetime(2026, 9, 28))
    assert schedule.day_matches(datetime(2026, 10, 1))
    assert not schedule.day_matches(datetime(2026, 9, 29))


@pytest.mark.parametrize("expression", [
    "@daily", "* * * *", "* * * * * *", "61 * * * *", "*/0 * * * *", "5-1 * * * *",
    "L * * * *", "0 0 ? * *", "",
])
def test_anything_outside_the_grammar_is_refused(expression):
    with pytest.raises(CronParseError):
        parse_cron(expression)
    assert next_fire_text(expression, datetime.now(timezone.utc)) is None


def test_an_impossible_date_has_no_next_fire():
    assert next_fire(parse_cron("0 0 31 2 *"), datetime.now(timezone.utc)) is None


def test_search_cost_is_bounded_for_a_rare_date():
    start = datetime.now(timezone.utc)
    fire = next_fire(parse_cron("0 0 29 2 *"), start)
    assert fire is not None and fire - start < timedelta(days=4 * 366 + 1)

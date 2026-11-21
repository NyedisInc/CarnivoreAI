
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, FrozenSet, Iterable

from src.core.timeline.parity import MAX_DAYS, Parity
from src.core.timeline.parity_days import REAL, DayTally

STATES = frozenset({"a", "b", "c"})
FIRST = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def _day(offset: int, states: Iterable[str], *, decided: int = 10, canary: int = 1, canary_light: int = 1) -> DayTally:
    tally = DayTally((FIRST + timedelta(days=offset)).date().isoformat(), transcript_decided=decided)
    for state in states:
        tally.by_state[state] = 1
    tally.canary[REAL], tally.canary_light[REAL] = canary, canary_light
    return tally


def _parity(days: Iterable[DayTally], required: FrozenSet[str] = STATES) -> Parity:
    counter = Parity(min_comparisons=5, required_states=required, enabled=lambda: True, store_path=lambda: None)
    counter._ensure_loaded()
    for tally in days:
        counter._days[tally.day] = tally
    return counter


def _counted(counter: Parity) -> Dict[str, bool]:
    return {day["day"]: day["counted"] for day in counter.snapshot()["days"]}


def test_states_spread_across_the_week_count() -> None:
    counter = _parity([_day(0, "a"), _day(1, "b"), _day(2, "c")])
    verdict = _counted(counter)
    assert [verdict[_day(i, "").day] for i in range(3)] == [False, False, True], verdict
    assert counter.snapshot()["counted_days"] == 1


def test_a_state_older_than_seven_days_falls_out_of_the_window() -> None:
    days = [_day(0, "c")] + [_day(i, "ab") for i in range(1, 8)]
    verdict = _counted(_parity(days))
    assert verdict[_day(6, "").day] is True, "day 6 window is days 0 to 6 and holds c"
    assert verdict[_day(7, "").day] is False, "day 7 window is days 1 to 7 and lost c"


def test_a_day_failing_its_own_floors_never_counts_however_complete_the_week() -> None:
    days = [_day(0, "abc"), _day(1, "", decided=1), _day(2, "", canary=0), _day(3, "", canary_light=0)]
    verdict = _counted(_parity(days))
    assert [verdict[_day(i, "").day] for i in range(4)] == [True, False, False, False], verdict


def test_the_report_names_the_states_the_week_is_missing() -> None:
    snapshot = _parity([_day(0, "a"), _day(1, "a")]).snapshot()
    assert snapshot["days"][0]["week_states_missing"] == ["b", "c"], snapshot["days"][0]
    assert snapshot["week_states_missing"] == ["b", "c"], snapshot
    assert snapshot["window_days"] == 7


def test_the_memory_keeps_at_least_the_seven_day_window() -> None:
    assert MAX_DAYS >= 7


def test_a_day_failing_its_floors_still_supplies_its_states_to_a_later_full_day() -> None:
    verdict = _counted(_parity([_day(0, "ab", decided=1), _day(1, "c")]))
    assert verdict[_day(0, "").day] is False, "day 0 fails its own comparison floor"
    assert verdict[_day(1, "").day] is True, "day 1 passes its floors and the pooled week holds a, b and c"


def test_a_gap_day_inside_the_window_adds_no_states_and_breaks_nothing() -> None:
    verdict = _counted(_parity([_day(0, "a"), _day(2, "bc"), _day(9, "bc")]))
    assert list(verdict) == [_day(i, "").day for i in (9, 2, 0)], "a missing date never appears as a day"
    assert verdict[_day(2, "").day] is True, "the window holds day 0's a across the gap"
    assert verdict[_day(9, "").day] is False, "day 9's window is days 3 to 9 and holds no a"


def test_a_single_day_store_at_startup_needs_every_state_that_day() -> None:
    assert _counted(_parity([_day(0, "abc")])) == {_day(0, "").day: True}
    snapshot = _parity([_day(0, "a")]).snapshot()
    assert snapshot["days"][0]["counted"] is False
    assert snapshot["week_states_missing"] == ["b", "c"]

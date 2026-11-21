
from __future__ import annotations

from src.core.mass_death.detector import MIN_DEATHS, WINDOW_SECONDS, MassDeathDetector


def _det() -> MassDeathDetector:
    return MassDeathDetector()


def test_constants_are_the_ruled_numbers():
    assert (MIN_DEATHS, WINDOW_SECONDS) == (3, 10.0)


def test_three_deaths_in_one_pass_make_an_event():
    event = _det().record(["a", "b", "c"], now=100.0)
    assert event is not None
    assert (event.count, event.session_uuids, event.at) == (3, ("a", "b", "c"), 100.0)


def test_one_or_two_deaths_make_no_event():
    det = _det()
    assert det.record(["a"], now=1.0) is None
    assert det.record(["b"], now=2.0) is None


def test_deaths_spread_past_the_window_make_no_event():
    det = _det()
    assert det.record(["a"], now=0.0) is None
    assert det.record(["b"], now=6.0) is None
    assert det.record(["c"], now=12.0) is None


def test_deaths_across_passes_inside_the_window_add_up():
    det = _det()
    assert det.record(["a", "b"], now=0.0) is None
    event = det.record(["c"], now=4.0)
    assert event is not None and event.count == 3


def test_a_burst_reports_once_and_again_only_when_it_grows():
    det = _det()
    assert det.record(["a", "b", "c"], now=0.0) is not None
    assert det.record([], now=1.0) is None
    assert det.record(["a"], now=2.0) is None
    grown = det.record(["d"], now=3.0)
    assert grown is not None and grown.count == 4


def test_a_new_burst_after_a_quiet_window_reports_again():
    det = _det()
    assert det.record(["a", "b", "c"], now=0.0) is not None
    assert det.record([], now=30.0) is None
    again = det.record(["x", "y", "z"], now=31.0)
    assert again is not None and again.session_uuids == ("x", "y", "z")


def test_last_event_is_kept_for_the_action():
    det = _det()
    assert det.last_event is None
    det.record(["a", "b", "c"], now=0.0)
    assert det.last_event is not None and det.last_event.count == 3

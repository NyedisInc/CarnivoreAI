
from __future__ import annotations

from datetime import datetime

import pytest

from src.core.notifications import extras
from src.core.notifications.routing_view import QuietHours


def at(h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, 3, h, m)


@pytest.mark.parametrize("q,h,m,expect", [
    (("22:00", "07:00"), 23, 30, True), (("22:00", "07:00"), 6, 59, True), (("22:00", "07:00"), 7, 0, False),
    (("22:00", "07:00"), 22, 0, True), (("22:00", "07:00"), 12, 0, False), (("09:00", "17:00"), 12, 0, True),
    (("09:00", "17:00"), 17, 0, False), (("09:00", "09:00"), 9, 0, False), (("bad", "17:00"), 12, 0, False),
    (("25:00", "17:00"), 12, 0, False),
])
def test_quiet_hours(q, h, m, expect):
    assert extras.in_quiet_hours(QuietHours(*q), at(h, m)) is expect


def test_quiet_none_and_passes():
    assert extras.in_quiet_hours(None, at(3)) is False
    assert extras.passes_quiet_hours("session.permission") and not extras.passes_quiet_hours("session.finished")
    assert not extras.passes_quiet_hours("nope")


def test_project_filter():
    assert extras.project_allowed((), "x") and extras.project_allowed(("a",), "") and extras.project_allowed(("a",), "a")
    assert not extras.project_allowed(("a",), "b")


def test_away_and_reminder():
    assert extras.should_hold_for_away(True, True) and not extras.should_hold_for_away(True, False)
    assert not extras.should_hold_for_away(False, True)
    assert extras.reminder_delay_seconds("session.question", None) == 600.0
    assert extras.reminder_delay_seconds("session.question", 3) == 180.0
    assert extras.reminder_delay_seconds("session.question", 0) is None
    assert extras.reminder_delay_seconds("session.finished", 10) is None

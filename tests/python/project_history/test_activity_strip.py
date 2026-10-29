from datetime import datetime, timezone

from src.core.project_history import build_history
from src.core.project_history.activity import ACTIVITY_DAYS, activity_days, is_automated
from src.core.project_history.query import HistoryQuery, RowFacts

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _row(**kw):
    base = {"session_uuid": "u", "project_id": 1, "lifecycle": "stopped", "lifecycle_source": "tmux_missing"}
    base.update(kw)
    return base


def test_counts_only_days_a_stored_instant_falls_on():
    days = activity_days([_row(created_at="2026-09-20T01:00:00Z", last_work_at="2026-09-25T09:00:00Z")], NOW)
    assert len(days) == ACTIVITY_DAYS
    assert days[-1] == 0 and days[-5] == 1 and days[-10] == 1
    assert sum(days) == 2, "nothing is interpolated between two known instants"


def test_running_row_fills_every_day_up_to_today():
    days = activity_days([_row(lifecycle="running", created_at="2026-09-27T01:00:00Z")], NOW)
    assert days[-3:] == [1, 1, 1] and sum(days) == 3


def test_instants_outside_the_window_are_ignored():
    assert sum(activity_days([_row(created_at="2026-08-01T00:00:00Z", last_work_at="2026-08-02T00:00:00Z")], NOW)) == 0


def test_group_carries_the_strip_and_automated_counts():
    projects = [{"id": 1, "display_name": "alpha", "root": "/x/alpha", "archived_at": None}]
    rows = [_row(session_uuid="a", kind="automated", created_at="2026-09-29T01:00:00Z"),
            _row(session_uuid="b", created_at="2026-09-28T01:00:00Z")]
    result = build_history(projects, rows, HistoryQuery.parse(), RowFacts(lambda r: None))
    group = result["groups"][0]
    assert group["counts"]["closed"] == 2 and group["automated_counts"]["closed"] == 1
    assert len(group["activity_days"]) == ACTIVITY_DAYS
    assert is_automated(rows[0]) and not is_automated(rows[1])

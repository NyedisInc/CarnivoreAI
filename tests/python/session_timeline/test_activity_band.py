
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from src.core.session_timeline import activity, gather
from src.core.stats import config
from src.core.stats.store import StatsStore
from tests.python.bookmarks import fixtures
from tests.python.session_timeline.conftest import NOW, OLD
from tests.stats import seed

ACTIVITY_SQL = ("INSERT INTO activity_minutes (minute_ts,host,provider,conversation_id,project,model,agent_kind,"
                "observed_seconds,working_seconds) VALUES (?,?,?,?,?,?,?,?,?)")


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


@pytest.fixture
def stats(tmp_path):
    store = StatsStore(tmp_path / "stats-state")
    store.initialize()
    config.ensure_schema(store)
    return store


def _seed(store, conv, iso, observed, working):
    with store.connect() as db:
        seed.execute(db, ACTIVITY_SQL, (_ts(iso), "local", "claude", conv, "p", "opus", "session", observed, working))


def test_each_bar_carries_its_own_busy_seconds_and_nobody_elses(env, stats):
    for minute in ("10:00", "10:01", "10:02"):
        _seed(stats, OLD, f"2026-10-10T{minute}:00Z", 60, 30)
    _seed(stats, OLD, "2026-10-10T10:03:00Z", 60, 0)
    _seed(stats, fixtures.SOURCE, "2026-10-10T12:00:00Z", 60, 45)
    _seed(stats, "someone-else", "2026-10-10T12:00:00Z", 60, 60)
    answer = gather.build("7", now=NOW, stats_db=stats.db_path)
    by_conv = {b["conversation_id"]: b for b in answer["bars"]}
    assert by_conv[OLD]["busy_seconds"] == 90 and by_conv[fixtures.SOURCE]["busy_seconds"] == 45
    assert all(r["state"] == "busy" for r in by_conv[fixtures.SOURCE]["activity"])
    current = by_conv[fixtures.SOURCE]["activity"][0]
    assert current["start"] >= by_conv[fixtures.SOURCE]["started_at"]
    assert _ts(current["end"]) - _ts(current["start"]) <= 60


def test_a_narrow_window_is_read_by_the_minute_with_busy_and_idle_runs(stats):
    conv = "conv-narrow"
    for minute, working in (("10:00", 30), ("10:01", 30), ("10:02", 30), ("10:03", 0), ("10:04", 0)):
        _seed(stats, conv, f"2026-10-10T{minute}:00Z", 60, working)
    _seed(stats, conv, "2026-10-10T10:06:00Z", 60, 20)
    answer = {"bars": [{"conversation_id": conv, "started_at": "2026-10-10T10:00:00Z", "ended_at": "2026-10-10T10:30:00Z"}]}
    bar = activity.attach(answer, stats.db_path)["bars"][0]
    assert [(r["state"], r["busy_seconds"]) for r in bar["activity"]] == [("busy", 90), ("idle", 0), ("busy", 20)]
    assert bar["activity"][0]["end"].startswith("2026-10-10T10:03") and bar["activity"][2]["start"].startswith("2026-10-10T10:06")
    assert bar["busy_seconds"] == 110


def test_a_conversation_the_stats_never_measured_is_null_not_idle(env, stats):
    _seed(stats, fixtures.SOURCE, "2026-10-10T12:00:00Z", 60, 45)
    by_conv = {b["conversation_id"]: b for b in gather.build("7", now=NOW, stats_db=stats.db_path)["bars"]}
    assert by_conv[OLD]["activity"] is None and by_conv[OLD]["busy_seconds"] is None


def test_no_stats_file_means_no_band_and_the_timeline_still_answers(env, tmp_path):
    answer = gather.build("7", now=NOW, stats_db=tmp_path / "absent" / "stats.db")
    assert answer["bars"] and all(b["activity"] is None for b in answer["bars"])


def test_one_query_serves_every_bar(env, stats, monkeypatch):
    calls = []
    real = activity.read_cells
    monkeypatch.setattr(activity, "read_cells", lambda *a, **k: calls.append(a) or real(*a, **k))
    gather.build("7", now=NOW, stats_db=stats.db_path)
    assert len(calls) == 1 and sorted(w.conversation_id for w in calls[0][1]) == sorted([OLD, fixtures.SOURCE])


def test_an_unreadable_stats_file_is_logged_and_gives_no_band(env, tmp_path):
    bad = tmp_path / "bad.db"
    with sqlite3.connect(bad) as conn:
        conn.execute("CREATE TABLE unrelated (x)")
    answer = gather.build("7", now=NOW, stats_db=bad)
    assert all(b["activity"] is None for b in answer["bars"])


def test_the_grain_keeps_a_long_window_inside_the_cell_cap():
    assert activity.grain_for(3600) == 60
    assert activity.grain_for(7 * 86400) == 3600
    assert activity.grain_for(10 * 365 * 86400) == activity.GRAINS[-1]


def test_runs_merge_touching_cells_and_break_on_an_unmeasured_stretch():
    cells = [activity.Cell(0, 60, 10, 60), activity.Cell(60, 60, 5, 60), activity.Cell(180, 60, 0, 60),
             activity.Cell(240, 60, 0, 0), activity.Cell(300, 60, 0, 60)]
    found = activity.runs(cells, 0, 330)
    assert [(r["state"], r["busy_seconds"]) for r in found] == [("busy", 15), ("idle", 0), ("idle", 0)]
    assert found[-1]["end"] == datetime.fromtimestamp(330, tz=timezone.utc).isoformat()


def test_the_route_answer_carries_the_band(env, stats, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import session_timeline_routes
    from src.api.auth import require_auth

    _seed(stats, fixtures.SOURCE, "2026-10-10T12:00:00Z", 60, 45)
    monkeypatch.setattr(gather, "_db_path", lambda: env["db"])
    monkeypatch.setattr(gather, "_stats_db", lambda db: stats.db_path)
    app = FastAPI()
    app.include_router(session_timeline_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: "owner"
    bars = TestClient(app).get("/api/v1/sessions/7/timeline").json()["bars"]
    current = next(b for b in bars if b["current"])
    assert current["activity"][0]["state"] == "busy" and current["busy_seconds"] == 45


def test_a_one_hour_bar_inside_a_months_long_session_is_read_by_the_minute(stats):
    conv = "conv-long"
    for minute in range(60):
        _seed(stats, conv, f"2026-10-10T09:{minute:02d}:00Z", 60, 60)
    for minute, working in (("11:00", 45), ("11:01", 0), ("11:02", 30)):
        _seed(stats, conv, f"2026-10-10T{minute}:00Z", 60, working)
    answer = {"bars": [
        {"conversation_id": "conv-old", "started_at": "2026-07-01T00:00:00Z", "ended_at": "2026-10-10T11:00:00Z"},
        {"conversation_id": conv, "started_at": "2026-10-10T11:00:00Z", "ended_at": "2026-10-10T12:00:00Z"}]}
    bar = activity.attach(answer, stats.db_path)["bars"][1]
    assert [r["state"] for r in bar["activity"]] == ["busy", "idle", "busy"]
    assert bar["busy_seconds"] == 75 and bar["busy_seconds"] <= 3600


def test_a_clipped_hour_row_keeps_only_its_share_of_the_seconds_worked(stats):
    conv = "conv-hour"
    with stats.connect() as db:
        db.execute("UPDATE stat_retention SET minute_floor = ? WHERE singleton = 1", (_ts("2026-10-11T00:00:00Z"),))
    _seed(stats, conv, "2026-10-10T10:00:00Z", 3600, 3600)
    answer = {"bars": [{"conversation_id": conv, "started_at": "2026-10-10T10:30:00Z",
                        "ended_at": "2026-10-10T11:00:00Z"}]}
    bar = activity.attach(answer, stats.db_path)["bars"][0]
    assert bar["busy_seconds"] == 1800


def test_a_coarse_bucket_across_the_retention_floor_is_one_cell(stats):
    conv = "conv-floor"
    floor = _ts("2026-10-10T02:00:00Z")
    with stats.connect() as db:
        db.execute("UPDATE stat_retention SET minute_floor = ? WHERE singleton = 1", (floor,))
    _seed(stats, conv, "2026-10-10T01:00:00Z", 3600, 0)
    _seed(stats, conv, "2026-10-10T02:30:00Z", 60, 30)
    start, end = "2026-09-12T00:00:00Z", "2026-10-12T00:00:00Z"
    assert activity.grain_for(_ts(end) - _ts(start)) == 14400
    bar = activity.attach({"bars": [{"conversation_id": conv, "started_at": start, "ended_at": end}]},
                          stats.db_path)["bars"][0]
    starts = [r["start"] for r in bar["activity"]]
    assert len(starts) == len(set(starts)) == 1
    assert bar["activity"][0]["state"] == "busy" and bar["busy_seconds"] == 30


def test_runs_never_give_two_runs_for_one_start():
    found = activity.runs([activity.Cell(0, 14400, 600, 3600), activity.Cell(0, 14400, 0, 1800)], 0, 14400)
    assert [(r["state"], r["busy_seconds"]) for r in found] == [("busy", 600)]


def test_a_pass_that_moved_activity_names_the_timeline_topic(tmp_path, monkeypatch):
    from src.core import resource_push
    from src.core.resource_push import topics
    from src.core.stats.activity import ActivityPoint, ActivityRecorder
    from tests.stats.test_observations import ready

    sent = []
    monkeypatch.setattr(resource_push, "notify_coalesced", lambda *a: sent.append(a))
    recorder = ActivityRecorder(ready(tmp_path))

    def point(at, state):
        return ActivityPoint(instance="one", conversation_id="c", provider="claude", project="p", model="m",
                             host="local", state=state, observed_at=at, running=True)

    recorder.record([point(100, "working")], 100, [])
    assert sent == []
    recorder.record([point(110, "working")], 110, [])
    assert sent == [(topics.SESSION_TIMELINE, "stats_activity", 60.0)]


def test_a_stalled_wall_clock_does_not_drop_the_band(stats, monkeypatch):
    for minute in range(60):
        _seed(stats, "conv-a", f"2026-10-10T11:{minute:02d}:00Z", 60, 45 if minute == 0 else 0)
    real, calls = activity.time.monotonic, []

    def stalled():
        calls.append(1)
        return real() + (2.0 if len(calls) > 1 else 0.0)

    monkeypatch.setattr(activity.time, "monotonic", stalled)
    bar = activity.attach({"bars": [{"conversation_id": "conv-a", "started_at": "2026-10-10T11:00:00Z",
                                     "ended_at": "2026-10-10T12:00:00Z"}]}, stats.db_path)["bars"][0]
    assert bar["activity"] and bar["busy_seconds"] == 45

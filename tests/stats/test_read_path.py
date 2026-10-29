from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from src.core.stats import activity_query, config, queries, query_buckets
from src.core.stats.catalog import METRICS
from src.core.stats.plugin import progress as progress_mod
from src.core.stats.store import StatsStore
from src.models import stats as models
from src.models.stats import QueryRequest
from tests.stats import seed
from tests.stats.test_batch_live import _client, _item, _row

T0 = int(datetime(2026, 3, 8, 0, 0, tzinfo=timezone.utc).timestamp())
ACTIVITY_SQL = ("INSERT INTO activity_minutes (minute_ts,host,provider,conversation_id,project,model,agent_kind,"
                "observed_seconds,working_seconds,running_seconds,starts,completions,waiting_seconds,"
                "subagent_seconds) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)")


@pytest.fixture
def store(tmp_path):
    s = StatsStore(tmp_path)
    s.initialize()
    config.ensure_schema(s)
    with s.connect() as db:
        db.execute("UPDATE stats_settings SET enabled=1")
    return s


def _seed_activity(store) -> int:
    rows = 0
    with store.connect() as db:
        db.execute("UPDATE stat_retention SET minute_floor=? WHERE singleton=1", (T0 + 12 * 3600,))
        for i in range(0, 36 * 60, 3):
            stamp = T0 + i * 60
            for k in range(1 + i % 3):
                conv = f"c{(i + k) % 4}"
                observed = 0 if (i + k) % 11 == 0 else 5 + (i + k) % 40
                seed.execute(db, ACTIVITY_SQL, (
                    stamp, "local", "claude" if k % 2 == 0 else "codex", conv, f"p{(i // 3 + k) % 3}",
                    f"m{k % 2}", "main", observed, observed / 3 + 0.1, observed / 2, i % 2, (i + 1) % 2,
                    0.25 * k, 0.125 * k))
                rows += 1
            if i % 9:
                seed.execute(db, "INSERT INTO stats_observation_coverage VALUES (?,?)", (stamp, 30 + i % 50))
    return rows


def _old_new(store, metric: str, group_by, filters=None):
    request = QueryRequest.model_validate({
        "metric": metric, "operation": "summary", "from": datetime.fromtimestamp(T0, timezone.utc).isoformat(),
        "to": datetime.fromtimestamp(T0 + 36 * 3600, timezone.utc).isoformat(), "resolution": "hour",
        "group_by": group_by, "filters": filters or {}})
    start, end = query_buckets.minute_window(request)
    zone = ZoneInfo("UTC")
    deadline = time.monotonic() + 30
    old_rows = queries._fetch(store, "activity_minutes", request.filters, start, end, group_by, deadline, metric)
    old_cells, old_cov = queries._aggregate(old_rows, metric, "hour", zone, group_by, deadline)
    old_conv = len({r["conversation_id"] for r in old_rows if r["conversation_id"]})
    where, args = queries._where("activity_minutes", request.filters, start, end)
    new_rows, new_conv = activity_query.fetch_aggregated(
        store, metric, where, args, request.filters.model_dump(exclude_none=True), start, end, group_by, deadline,
        queries.MAX_ROWS, query_buckets.QueryLimit, True)
    new_cells, new_cov = queries._aggregate_activity(new_rows, metric, "hour", zone, group_by, deadline)
    return old_cells, old_cov, old_conv, new_cells, new_cov, new_conv


def test_batch_item_past_its_budget_does_not_zero_the_rest(tmp_path, monkeypatch):
    _, store = _client(tmp_path)
    now = int(time.time()) // 60 * 60
    _row(store, now, "c1")
    monkeypatch.setattr(queries, "DEADLINE_SECONDS", 0.2)
    real = queries.execute
    calls = []

    def slow_first(store_, request, deadline=None):
        calls.append(request.metric)
        if len(calls) == 1:
            time.sleep(0.3)
        return real(store_, request, deadline)

    monkeypatch.setattr(queries, "execute", slow_first)
    items = [{**_item(3600), "metric": "total_tokens"}, {**_item(3600), "metric": "input_tokens"},
             {**_item(3600), "metric": "output_tokens"}, {**_item(3600), "metric": "cache_read_tokens"}]
    results = queries.execute_batch(store, items)["results"]
    assert len(calls) == 4
    assert results[0]["ok"] is False and results[0]["error"]["code"] == "stats_query_limit"
    assert [r["ok"] for r in results[1:]] == [True, True, True]
    assert results[1]["result"]["summary"]["value"] == 100


@pytest.mark.parametrize("group_by", [None, "project", "model", "conversation_id"])
def test_aggregated_activity_equals_the_per_row_path(store, group_by):
    assert _seed_activity(store) > 100
    plain = [m for m, (_, table) in METRICS.items() if table == "activity_minutes" and not m.startswith("average_")]
    average = [m for m, (_, table) in METRICS.items() if table == "activity_minutes" and m.startswith("average_")]
    assert set(plain) == set(activity_query.PLAIN_METRICS) and len(average) == 2
    checked = 0
    for metric in plain + average:
        for filters in (None, {"provider": "claude"}, {"project": "p1", "model": "m0"}):
            old_cells, old_cov, old_conv, new_cells, new_cov, new_conv = _old_new(store, metric, group_by, filters)
            assert old_cells, (metric, group_by, filters)
            assert set(old_cells) == set(new_cells)
            for key, old in old_cells.items():
                new = new_cells[key]
                assert math.isclose(old["sum"], new["sum"], rel_tol=1e-6, abs_tol=1e-6), (metric, key)
                assert (old["count"], old["samples"], old["sample_minutes"]) == (
                    new["count"], new["samples"], new["sample_minutes"])
                if metric.startswith("average_"):
                    assert old["observed_by_minute"] == new["observed_by_minute"]
            for field in ("minute_rows", "unknown_value_rows", "quality_rows", "observed_minutes", "price_versions"):
                assert old_cov[field] == new_cov[field], (metric, field)
            for field in ("known_agent_seconds", "unknown_agent_seconds"):
                assert math.isclose(old_cov[field], new_cov[field], rel_tol=1e-6, abs_tol=1e-6), (metric, field)
            assert old_conv == new_conv
            checked += 1
    assert checked == 9 * 3
    assert _old_new(store, "average_working_agents", None)[1]["unknown_agent_seconds"] > 0


def test_rolling_windows_are_minute_floored_and_comparison_is_equal_length(monkeypatch):
    base = datetime(2026, 3, 8, 10, 0, 0, tzinfo=timezone.utc).timestamp()
    raw = {"metric": "total_tokens", "operation": "comparison", "rolling": "7d"}
    windows = []
    for offset in (5.0, 35.0):
        monkeypatch.setattr(models, "_clock", lambda offset=offset: base + offset)
        windows.append(QueryRequest.model_validate(raw))
    first, second = windows
    assert (first.from_, first.to) == (second.from_, second.to)
    assert first.to.timestamp() == base + 60 and first.to.timestamp() - first.from_.timestamp() == 7 * 86400
    assert first.comparison.to == first.from_
    assert first.comparison.to.timestamp() - first.comparison.from_.timestamp() == 7 * 86400
    monkeypatch.setattr(models, "_clock", lambda: base + 61.0)
    assert QueryRequest.model_validate(raw).to.timestamp() == base + 120
    with pytest.raises(ValueError):
        QueryRequest.model_validate({**raw, "rolling": "5d"})
    exact = QueryRequest.model_validate({"metric": "total_tokens", "from": "2026-03-01T00:00:00Z",
                                         "to": "2026-03-02T00:00:00Z"})
    assert exact.rolling is None and exact.to.day == 2


def test_rolling_batch_answers_echo_the_window_and_hit_the_cache(tmp_path):
    client, store = _client(tmp_path)
    _row(store, int(time.time()) // 60 * 60, "c1")
    item = {"metric": "total_tokens", "operation": "comparison", "rolling": "24h"}
    first = client.post("/api/v1/stats/query-batch", json={"items": [item]}).json()["results"][0]
    assert first["ok"] is True, first
    result = first["result"]
    assert result["rolling"] == "24h" and result["effective_range"]["from"] < result["effective_range"]["to"]
    assert result["comparison"]["range"]["to"] == result["effective_range"]["from"]
    assert result["summary"]["value"] == 150


def test_coverage_matches_the_view_and_the_route_never_waits_on_progress(tmp_path, monkeypatch):
    client, store = _client(tmp_path)
    now = int(time.time()) // 60 * 60
    for i in range(6):
        _row(store, now - i * 60, f"c{i}", model="<synthetic>" if i == 0 else "m1", cost=None if i % 2 else 5, out=0 if i == 0 else 50,
             inp=0 if i == 0 else 100)
    with store.connect(readonly=True) as db:
        view = db.execute(
            "SELECT MIN(minute_ts),MAX(minute_ts),COUNT(*),SUM(CASE WHEN estimated_cost_nano_usd IS NULL THEN 1 ELSE 0 END) "
            "FROM minute_usage WHERE (model!='<synthetic>' OR input_tokens+cache_write_tokens+cache_read_tokens+output_tokens!=0)"
        ).fetchone()
    fast = queries.coverage(store)
    assert view[2] == 5 and fast["minute_rows"] == view[2]
    assert fast["unknown_cost_rows"] == view[3] > 0
    assert fast["earliest"] == query_buckets.iso_utc(view[0]) and fast["latest"] == query_buckets.iso_utc(view[1])

    calls = []
    monkeypatch.setattr(progress_mod, "progress", lambda d: calls.append(1) or {"known_sources": 3, "pending_sources": 1})
    progress_mod._cache.clear()

    class Scheduler:
        def status(self):
            return {"state": "ok"}

    client.app.state.stats_scheduler = Scheduler()
    for _ in range(3):
        body = client.get("/api/v1/stats/coverage").json()
        assert body["collector"]["collector"] == {"known_sources": 3, "pending_sources": 1}
    assert calls == [1]
    progress_mod._cache.clear()

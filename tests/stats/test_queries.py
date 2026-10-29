from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

import pytest

from tests.stats import seed
from src.core.stats import config, project_groups, queries
from src.core.stats.store import StatsStore
from src.core.stats.plugin.extract import project_key
from src.core.db import db_path_for
from src.models.stats import QueryRequest


@pytest.fixture
def store(tmp_path):
    value = StatsStore(tmp_path)
    value.initialize()
    config.ensure_schema(value)
    return value


def _query(metric="total_tokens", **kwargs):
    return QueryRequest.model_validate({
        "metric": metric, "from": "2026-03-08T06:00:00Z",
        "to": "2026-03-08T08:00:00Z", **kwargs,
    })


def test_minute_totals_and_unknown_price_remain_disclosed(store):
    with store.connect() as db:
        seed.executemany(db,
            "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (1772949600, "local", "claude", "a", "/secret/Project", "opus", "main",
                 10, 2, 3, 4, 1000, "v1", 1, 1, 0, "ok"),
                (1772953200, "local", "claude", "b", "/secret/Project", "opus", "main",
                 5, 0, 0, 1, None, None, 1, 0, 1, "partial"),
            ],
        )
    tokens = queries.execute(store, _query(resolution="hour", timezone="America/New_York"))
    assert tokens["summary"] is None
    assert sum(point["value"] for point in tokens["series"][0]["points"]) == 25
    assert len(tokens["series"][0]["points"]) == 2
    assert any(point["value"] is None for point in tokens["series"][0]["points"]) is False
    minute = queries.execute(store, _query(resolution="auto"))
    assert any(point["value"] is None for point in minute["series"][0]["points"])
    cost = queries.execute(store, _query("estimated_cost_nano_usd", operation="summary"))
    assert cost["summary"]["value"] == 1000
    assert cost["coverage"]["unknown_value_rows"] == 1
    assert cost["coverage"]["unpriced_usage_count"] == 1
    assert cost["coverage"]["partial"] is True
    cost_timeline = queries.execute(store, _query("estimated_cost_nano_usd", resolution="hour"))
    assert cost_timeline["series"][0]["points"][1]["value"] is None
    assert cost_timeline["series"][0]["points"][1]["samples"] == 1
    ranking = queries.execute(store, _query(group_by="project", operation="ranking"))
    assert ranking["ranking"][0]["key"].startswith("project:")
    assert "/secret/" not in str(ranking)
    per_conversation = queries.execute(store, _query(operation="summary", transform="per_conversation"))
    assert per_conversation["summary"]["value"] == 12.5
    assert per_conversation["unit"] == "tokens/conversation"
    assert per_conversation["base_unit"] == "tokens"
    cumulative = queries.execute(store, _query(transform="cumulative", resolution="hour"))
    assert [point["value"] for point in cumulative["series"][0]["points"]] == [19, 25]


def test_resolution_and_series_budgets(store):
    with pytest.raises(queries.QueryLimit):
        queries.execute(store, _query(resolution="minute", to="2026-03-09T08:00:00Z"))
    with pytest.raises(ValueError):
        _query(timezone="Invented/Nowhere")
    with pytest.raises(ValueError):
        _query(filters={"provider": "claude' OR 1=1 --"})


def test_activity_average_uses_observed_duration(store):
    with store.connect() as db:
        seed.execute(db, "INSERT INTO activity_minutes (minute_ts,host,provider,conversation_id,project,model,agent_kind,observed_seconds,working_seconds,running_seconds,starts,completions) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (1772949600, "local", "claude", "a", "p", "opus", "main",
                    20, 10, 15, 0, 0))
        seed.execute(db, "INSERT INTO stats_observation_coverage VALUES (?,?)", (1772949600, 20))
    result = queries.execute(store, _query("average_working_agents", operation="summary"))
    assert result["summary"]["value"] == 0.5
    running = queries.execute(store, _query("average_running_agents", operation="summary"))
    assert running["summary"]["value"] == 0.75


def test_disjoint_agent_observations_are_partial_lower_bound(store):
    stamp = int(datetime.fromisoformat("2026-03-08T06:00:00+00:00").timestamp())
    with store.connect() as db:
        seed.execute(db, "INSERT INTO stats_observation_coverage VALUES (?,?)", (stamp, 30))
        for conversation in ("a", "b"):
            seed.execute(db, "INSERT INTO activity_minutes (minute_ts,host,provider,conversation_id,project,model,agent_kind,observed_seconds,working_seconds,running_seconds,starts,completions) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (stamp, "local", "claude", conversation, "p", "opus", "main",
                        15, 15, 15, 0, 0))
    result = queries.execute(store, _query("average_working_agents", operation="summary"))
    assert result["summary"]["value"] == 1
    assert result["coverage"]["known_agent_seconds"] == 30
    assert result["coverage"]["unknown_agent_seconds"] == 30
    assert result["coverage"]["partial"] is True


def test_rate_clips_dst_calendar_bucket_to_requested_hour(store):
    stamp = int(datetime.fromisoformat("2026-03-08T06:30:00+00:00").timestamp())
    with store.connect() as db:
        seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (stamp, "local", "claude", "a", "p", "opus", "main",
                    3600, 0, 0, 0, 1000, "v1", 1, 1, 0, "ok"))
    request = _query(**{"from": "2026-03-08T06:30:00Z",
                                        "to": "2026-03-08T07:30:00Z",
                                        "resolution": "day", "timezone": "America/New_York",
                                        "transform": "rate"})
    result = queries.execute(store, request)
    assert result["series"][0]["points"][0]["value"] == 1
    assert result["unit"] == "tokens/second"
    assert result["base_unit"] == "tokens"
    assert queries._bucket_bounds("2026-03-08T00:00:00-05:00", "day",
                                  __import__("zoneinfo").ZoneInfo("America/New_York"))[1] - \
           queries._bucket_bounds("2026-03-08T00:00:00-05:00", "day",
                                  __import__("zoneinfo").ZoneInfo("America/New_York"))[0] == 23 * 3600


def test_comparison_keeps_primary_groups_and_other_normalizes_conversations(store):
    primary = int(datetime.fromisoformat("2026-03-08T06:00:00+00:00").timestamp())
    comparison = int(datetime.fromisoformat("2026-03-07T06:00:00+00:00").timestamp())
    with store.connect() as db:
        for ts, conversation, model, count in (
            (primary, "a", "A", 100), (primary, "b", "B", 20), (primary, "c", "C", 10),
            (comparison, "d", "D", 50)):
            seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (ts, "local", "claude", conversation, "p", model, "main",
                        count, 0, 0, 0, 1000, "v1", 1, 1, 0, "ok"))
    result = queries.execute(store, _query(
        group_by="model", top_n=1, transform="per_conversation", operation="comparison",
        comparison={"from": "2026-03-07T06:00:00Z", "to": "2026-03-07T08:00:00Z"}))
    assert [item["key"] for item in result["series"]] == ["A", "other"]
    assert [item["key"] for item in result["comparison"]["series"]] == ["A", "other"]
    assert result["comparison"]["series"][1]["points"][0]["value"] == 50
    assert result["ranking"] is None
    ranked = queries.execute(store, _query(group_by="model", top_n=1,
                                            transform="per_conversation", operation="ranking"))
    assert ranked["ranking"][1]["value"] == 15
    conversations = queries.execute(store, _query(group_by="conversation_id", operation="ranking"))
    assert conversations["ranking"][0]["filter_value"] == "a"


def test_mixed_price_same_minute_keeps_known_subtotal_and_partial_marker(store):
    stamp = int(datetime.fromisoformat("2026-03-08T06:00:00+00:00").timestamp())
    with store.connect() as db:
        seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (stamp, "local", "claude", "a", "p", "opus", "main",
                    100, 0, 0, 0, 100, "v1", 2, 1, 1, "unknown_price"))
    result = queries.execute(store, _query("estimated_cost_nano_usd", operation="summary"))
    assert result["summary"]["value"] == 100
    assert result["coverage"]["priced_usage_count"] == 1
    assert result["coverage"]["unpriced_usage_count"] == 1
    assert result["coverage"]["priced_token_total"] == 0
    assert result["coverage"]["unpriced_token_total"] == 0
    assert result["coverage"]["mixed_price_token_total"] == 100
    timeline = queries.execute(store, _query("estimated_cost_nano_usd", resolution="hour"))
    assert timeline["series"][0]["points"][0]["value"] == 100
    assert timeline["series"][0]["points"][0]["partial"] is True


def test_zero_token_synthetic_history_is_not_usage_or_unknown_cost(store):
    stamp = int(datetime.fromisoformat("2026-03-08T06:00:00+00:00").timestamp())
    with store.connect() as db:
        seed.executemany(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            (stamp, "local", "claude", "phantom", "p", "<synthetic>", "session",
             0, 0, 0, 0, None, None, 1, 0, 1, "ok"),
            (stamp, "local", "claude", "priced", "p", "opus", "session",
             10, 2, 3, 4, 1000, "v1", 1, 1, 0, "ok"),
            (stamp, "local", "claude", "unpriced", "p", "unknown", "session",
             5, 0, 0, 1, None, None, 1, 0, 1, "unknown_price"),
            (stamp, "local", "claude", "real-zero", "p", "unknown", "session",
             0, 0, 0, 0, None, None, 1, 0, 1, "unknown_price"),
        ])
    cost = queries.execute(store, _query("estimated_cost_nano_usd", operation="summary"))
    assert cost["summary"]["value"] == 1000
    assert cost["summary"]["contributing_conversations"] == 3
    assert cost["coverage"]["minute_rows"] == 3
    assert cost["coverage"]["unknown_value_rows"] == 2
    assert cost["coverage"]["priced_usage_count"] == 1
    assert cost["coverage"]["unpriced_usage_count"] == 2
    assert cost["coverage"]["priced_token_total"] == 19
    assert cost["coverage"]["unpriced_token_total"] == 6
    direct = queries.execute(store, _query("estimated_cost_nano_usd", operation="summary",
                                          transform="per_conversation"))
    assert direct["coverage"] == cost["coverage"]
    assert direct["summary"]["contributing_conversations"] == 3
    assert queries.coverage(store)["unknown_cost_rows"] == 2
    assert queries.coverage(store)["minute_rows"] == 3
    contributed = queries.contributions(store, _query("estimated_cost_nano_usd"), limit=10, cursor=0)
    assert {item["conversation_id"] for item in contributed["items"]} == {"priced", "unpriced", "real-zero"}
    dimensions = queries.dimensions(store, dimension="model", filters=_query().filters,
                                    start=stamp, end=stamp + 60, limit=10, cursor=0)
    assert {item["key"] for item in dimensions["items"]} == {"opus", "unknown"}


def test_project_dimension_uses_configured_name_without_exposing_path(store):
    project_groups.forget()
    known_path = "/private/projects/secret-workspace"
    sub_path = known_path + "/web"
    seen_path = "/private/projects/scratch-folder"
    unseen_path = "/private/projects/never-seen"
    with sqlite3.connect(db_path_for(store.state_dir)) as db:
        db.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, root TEXT, raw_path TEXT, display_name TEXT, archived_at TEXT)")
        db.execute("INSERT INTO projects (root,raw_path,display_name,archived_at) VALUES (?,?,?,NULL)",
                   (known_path, known_path, "Research dashboard"))
        db.execute("CREATE TABLE sessions (working_dir TEXT)")
        db.executemany("INSERT INTO sessions VALUES (?)", [(sub_path,), (seen_path,)])
    stamp = int(datetime.fromisoformat("2026-03-08T06:00:00+00:00").timestamp())
    with store.connect() as db:
        for conversation, path, tokens in (("a", known_path, 10), ("b", sub_path, 5),
                                           ("c", seen_path, 7), ("d", unseen_path, 3)):
            seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (stamp, "local", "claude", conversation, project_key(path), "opus", "session",
                        tokens, 0, 0, 0, 100, "v1", 1, 1, 0, "ok"))
    ranked = queries.execute(store, _query(group_by="project", operation="ranking"))["ranking"]
    assert [(item["label"], item["value"]) for item in ranked] == [
        ("Research dashboard", 15), ("2 folders outside projects", 10)]
    assert ranked[0]["filter_value"] == project_key(known_path)
    assert ranked[1]["filter_value"] is None
    assert ranked[1]["detail"] == {"count": 2, "folders": ["scratch-folder"], "unnamed": 1}
    dimension = queries.dimensions(store, dimension="project", filters=_query().filters,
                                   start=stamp, end=stamp + 60, limit=10, cursor=0)
    assert [item["label"] for item in dimension["items"]] == [item["label"] for item in ranked]
    assert dimension["total"] == 2
    assert "/private/" not in str(ranked) + str(dimension)
    assert "unknown" not in str(ranked).lower() + str(dimension).lower()
    assert queries._public_dimension("account_id", "account-123", account_labels={
        "account-123": "Work account"}) == ("account-123", "Work account", "account-123")
    assert queries._public_dimension("account_id", "gone-1", account_labels={})[1] == "account no longer configured"
    assert queries._public_dimension("subagent_type", "unknown")[1] == "no subagent type"


def test_price_version_union_expands_on_both_query_paths(store):
    stamp = int(datetime.fromisoformat("2026-03-08T06:00:00+00:00").timestamp())
    with store.connect() as db:
        seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (stamp, "local", "claude", "a", "p", "opus", "main",
                    100, 0, 0, 0, 100, "v1,v2", 2, 2, 0, "ok"))
    fast = queries.execute(store, _query("estimated_cost_nano_usd", operation="summary"))
    direct = queries.execute(store, _query("estimated_cost_nano_usd",
                                           operation="summary", transform="per_conversation"))
    assert fast["coverage"]["price_versions"] == ["v1", "v2"]
    assert direct["coverage"]["price_versions"] == ["v1", "v2"]

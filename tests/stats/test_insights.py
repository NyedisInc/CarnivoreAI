from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.stats import seed
from src.api.auth import require_auth
from src.api.stats_insight_routes import router
from src.core.stats import config, insights
from src.core.stats.store import StatsStore
from src.models.stats import AnnotationWrite, StatsFilters

MARK = int(datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc).timestamp())
NOW = MARK + 10 * 86400
DAY = 86400


@pytest.fixture
def store(tmp_path):
    value = StatsStore(tmp_path)
    value.initialize()
    config.ensure_schema(value)
    return value


def _usage(store, rows):
    with store.connect() as db:
        seed.executemany(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            (ts, "local", "claude", conv, "/secret/Path/proj", model, "main", tokens, 0, 0, 0, cost, "v1", 1,
             0 if cost is None else 1, 1 if cost is None else 0, "ok") for ts, conv, model, tokens, cost in rows])


def _marker(store) -> str:
    return config.create_annotation(store, AnnotationWrite(
        occurred_at=datetime.fromtimestamp(MARK, timezone.utc), label="claude.md tightened",
        kind="manual"))["id"]


def _seed_sides(store, before_cost, after_cost, after_model="opus"):
    rows = []
    for i, cost in enumerate(before_cost):
        rows.append((MARK - 2 * DAY + i * 60, f"b{i}", "sonnet", 100, cost))
    for i, cost in enumerate(after_cost):
        rows.append((MARK + 2 * DAY + i * 60, f"a{i}", after_model, 100, cost))
    _usage(store, rows)


def test_conversations_are_capped_ranked_and_carry_ids_and_names_only(store):
    total = insights.CONVERSATION_CAP + 20
    _usage(store, [(MARK + i * 60, f"c{i:04d}", "opus", 10 + i, 1000 + i) for i in range(total)])
    with store.connect() as db:
        seed.execute(db, "INSERT INTO conversation_meta(conversation_id,provider,first_minute,last_minute) VALUES (?,?,?,?)",
                     ("c0519", "claude", MARK - 3600, MARK + 7200))
    out = insights.conversations(store, start=MARK - 60, end=MARK + total * 60 + 60, filters=StatsFilters(), limit=10_000)
    assert len(out["items"]) == insights.CONVERSATION_CAP and out["total"] == total and out["truncated"]
    assert out["items"][0]["conversation_id"] == "c0519" and out["items"][0]["cost_nano_usd"] == 1519
    assert out["items"][0]["duration_seconds"] == 3600 + 7200 + 60
    assert out["items"][1]["duration_seconds"] == 60
    assert set(out["items"][0]) == {"conversation_id", "project", "model", "model_label", "tokens", "cost_nano_usd",
                                    "first_minute", "last_minute", "duration_seconds"}
    assert "secret" not in str(out)


def test_unpriced_conversation_cost_is_null_and_sorts_last(store):
    _usage(store, [(MARK, "priced", "opus", 5, 900), (MARK, "free", "opus", 500, None)])
    out = insights.conversations(store, start=MARK - 60, end=MARK + 60, filters=StatsFilters())
    assert [item["conversation_id"] for item in out["items"]] == ["priced", "free"]
    assert out["items"][1]["cost_nano_usd"] is None


def test_impact_is_deterministic_and_names_the_direction(store):
    _seed_sides(store, [100, 110, 120, 130, 140, 150], [500, 510, 520, 530, 540, 550])
    marker = _marker(store)
    first = insights.impact(store, annotation_id=marker, metric="estimated_cost_nano_usd", days=7, now=NOW)
    again = insights.impact(store, annotation_id=marker, metric="estimated_cost_nano_usd", days=7, now=NOW)
    assert first == again
    assert first["before"]["n"] == 6 and first["after"]["n"] == 6
    assert first["before"]["median"] == 125 and first["after"]["median"] == 525
    assert first["delta"]["absolute"] == 400 and first["delta"]["percent"] == pytest.approx(3.2)
    assert first["verdict"] == "higher" and first["interval"]["low"] > 0
    assert first["interval"]["iterations"] == insights.BOOTSTRAP_ITERATIONS
    assert first["mix"]["shifted"] and first["mix"]["distance"] == pytest.approx(1.0)
    other = insights.impact(store, annotation_id=marker, metric="estimated_cost_nano_usd", days=7, now=NOW, iterations=200)
    assert other["interval"]["iterations"] == 200


def test_impact_spanning_zero_is_no_clear_change_and_small_sides_are_insufficient(store):
    _seed_sides(store, [100, 300, 200, 250, 150, 180], [110, 290, 210, 240, 160, 170], after_model="sonnet")
    marker = _marker(store)
    same = insights.impact(store, annotation_id=marker, metric="estimated_cost_nano_usd", days=7, now=NOW)
    assert same["verdict"] == "no_clear_change" and not same["mix"]["shifted"]
    few = insights.impact(store, annotation_id=marker, metric="estimated_cost_nano_usd", days=7, now=MARK + DAY // 2)
    assert few["verdict"] == "insufficient" and few["interval"] is None and few["after"]["partial"]


def test_impact_refuses_a_future_marker_an_unknown_marker_and_a_bad_metric(store):
    marker = _marker(store)
    with pytest.raises(ValueError):
        insights.impact(store, annotation_id=marker, metric="estimated_cost_nano_usd", days=7, now=MARK - 5)
    with pytest.raises(ValueError):
        insights.impact(store, annotation_id=marker, metric="working_seconds", days=7, now=NOW)
    with pytest.raises(config.NotFound):
        insights.impact(store, annotation_id="550e8400-e29b-41d4-a716-446655440000", metric="total_tokens", days=7, now=NOW)


def test_routes_are_authenticated_and_bounded(store, tmp_path):
    config.ensure_schema(store)
    with store.connect() as db:
        db.execute("UPDATE stats_settings SET enabled=1")
    app = FastAPI()
    app.state.stats_store = store
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    span = {"from": "2026-09-20T00:00:00Z", "to": "2026-09-21T00:00:00Z"}
    assert client.get("/api/v1/stats/conversations", params=span).status_code == 401
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    assert client.get("/api/v1/stats/conversations", params=span).json()["items"] == []
    assert client.get("/api/v1/stats/conversations", params={**span, "limit": 501}).status_code == 422
    assert client.get("/api/v1/stats/conversations", params={"from": span["to"], "to": span["from"]}).status_code == 422
    assert client.get("/api/v1/stats/impact", params={"annotation_id": "550e8400-e29b-41d4-a716-446655440000"}).status_code == 404
    assert client.get("/api/v1/stats/impact", params={"annotation_id": "550e8400-e29b-41d4-a716-446655440000", "days": 31}).status_code == 422
    assert client.get("/api/v1/stats/impact", params={"annotation_id": "550e8400-e29b-41d4-a716-446655440000", "metric": "working_seconds"}).status_code == 422

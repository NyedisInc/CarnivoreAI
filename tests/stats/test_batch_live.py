from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.stats import seed
from src.api.auth import require_auth
from src.api.stats_routes import router
from src.core.stats import config, live_view, queries
from src.core.stats.store import StatsStore


def _client(tmp_path):
    store = StatsStore(tmp_path)
    store.initialize()
    config.ensure_schema(store)
    with store.connect() as db:
        db.execute("UPDATE stats_settings SET enabled=1")
    app = FastAPI()
    app.state.stats_store = store
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app), store


def _row(store, minute, conv, *, model="m1", inp=100, cw=0, cr=0, out=50, cost=1_000_000_000, project="a" * 24):
    with store.connect() as db:
        seed.execute(db,
            "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (minute, "local", "claude", conv, project, model, "main", inp, cw, cr, out, cost,
             "v1" if cost is not None else None, 1, 1 if cost is not None else 0,
             0 if cost is not None else 1, "ok"))


def _item(offset=3600):
    now = int(time.time()) // 60 * 60
    return {"from": _iso(now - offset), "to": _iso(now + 60), "metric": "total_tokens",
            "operation": "summary"}


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def test_batch_matches_single_memoizes_and_isolates_errors(tmp_path, monkeypatch):
    client, store = _client(tmp_path)
    now = int(time.time()) // 60 * 60
    _row(store, now, "c1")
    item = _item()
    single = client.post("/api/v1/stats/query", json=item).json()
    calls = []
    real = queries.execute
    monkeypatch.setattr(queries, "execute", lambda *a, **k: calls.append(1) or real(*a, **k))
    r = client.post("/api/v1/stats/query-batch", json={"items": [item, {"metric": "nope"}, dict(reversed(item.items()))]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["results"][0]["ok"] is True and body["results"][0]["result"] == single
    assert body["results"][0]["answer"]["stale"] is False
    assert body["results"][1]["ok"] is False and body["results"][1]["error"]["code"] == "invalid_stats_request"
    assert body["results"][2] == body["results"][0]
    assert body["revision"] == single["revision"]
    assert len(calls) == 1


def test_batch_limit_and_auth(tmp_path):
    client, _ = _client(tmp_path)
    assert client.post("/api/v1/stats/query-batch", json={"items": [_item()] * 33}).status_code == 422
    assert client.post("/api/v1/stats/query-batch", json={"items": []}).status_code == 422
    assert client.post("/api/v1/stats/query-batch", json={"items": [_item()] * 32}).status_code == 200
    client.app.dependency_overrides.clear()
    assert client.post("/api/v1/stats/query-batch", json={"items": [_item()]}).status_code == 401


def test_live_v2_nulls_without_data(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/api/v1/stats/live").json()
    assert body["available"] is False
    assert body["cache_hit_ratio_15m"] is None
    assert body["top_conversations_15m"] == [] and body["active_models_15m"] == []
    for w in ("5m", "15m", "60m"):
        assert body["burn"][w]["tokens_per_minute"] is None
        assert body["burn"][w]["estimated_usd_per_hour"] is None


def test_live_v2_window_math(tmp_path):
    client, store = _client(tmp_path)
    now = int(time.time()) // 60 * 60
    _row(store, now, "c1", inp=100, cr=300, cw=100, out=100)
    _row(store, now - 10 * 60, "c2", model="m2", inp=200, out=0, cost=None)
    _row(store, now - 30 * 60, "c3", inp=600, out=0)
    _row(store, now - 61 * 60, "c4", inp=9999)
    body = client.get("/api/v1/stats/live").json()
    assert body["burn"]["5m"]["tokens_per_minute"] == 600 / 5
    assert body["burn"]["15m"]["tokens_per_minute"] == 800 / 15
    assert body["burn"]["60m"]["tokens_per_minute"] == 1400 / 60
    assert body["burn"]["5m"]["estimated_usd_per_hour"] == 1.0 / 5 * 60
    assert body["burn"]["15m"]["estimated_usd_per_hour"] == 1.0 / 15 * 60
    assert body["cache_hit_ratio_15m"] == 300 / (500 + 200)
    top = body["top_conversations_15m"]
    assert [t["conversation_id"] for t in top] == ["c1", "c2"]
    assert top[0]["tokens"] == 600 and top[0]["estimated_cost_usd"] == 1.0
    assert top[1]["estimated_cost_usd"] is None and top[1]["model"] == "m2"
    assert set(body["active_models_15m"]) == {"m1", "m2"}


def test_live_v2_is_read_once_per_revision_and_minute(tmp_path, monkeypatch):
    client, store = _client(tmp_path)
    now = int(time.time()) // 60 * 60
    _row(store, now, "c1")
    runs = []
    real = live_view.live_v2
    monkeypatch.setattr(live_view, "live_v2", lambda *a, **k: runs.append(1) or real(*a, **k))
    first = client.get("/api/v1/stats/live").json()
    second = client.get("/api/v1/stats/live").json()
    assert len(runs) == 1
    assert first["burn"] == second["burn"] and first["burn"]["5m"]["tokens_per_minute"] is not None
    _row(store, now, "c2")
    with store.connect() as db:
        db.execute("UPDATE stats_meta SET value=value+1 WHERE key='revision'")
    client.get("/api/v1/stats/live")
    assert len(runs) == 2

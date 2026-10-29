from __future__ import annotations

import pytest
from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.stats_tripwire_routes import router
from src.core.stats import config, events, tripwires
from src.core.stats.store import StatsStore
from src.models.stats import TripwireWrite

BODY = {"name": "burn", "query": {"metric": "total_tokens"}, "comparator": ">",
        "threshold": 100, "for_minutes": 5, "cooldown_minutes": 30}


def _setup(tmp_path):
    store = StatsStore(tmp_path)
    store.initialize()
    config.ensure_schema(store)
    settings = config.get_settings(store)
    if not settings["enabled"]:
        config.update_settings(store, enabled=True, revision=settings["revision"])
    app = FastAPI()
    app.state.stats_store = store
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return store, TestClient(app)


def _feed(monkeypatch, box):
    monkeypatch.setattr(tripwires.queries, "execute",
                        lambda store, request: {"summary": {"value": box["value"]}})


def _create(client, **over):
    response = client.post("/api/v1/stats/tripwires", json={**BODY, **over})
    assert response.status_code == 201, response.text
    return response.json()


def _events(store):
    return [e["kind"] for e in reversed(events.list_events(
        store, start=0, end=2**31, kind=None, limit=100, cursor=0)["items"])]


def test_crud_validation_and_auth(tmp_path):
    store, client = _setup(tmp_path)
    made = _create(client)
    assert made["state"] == "unknown" and made["query"]["operation"] == "summary"
    assert client.put(f"/api/v1/stats/tripwires/{made['id']}", json={**BODY, "threshold": 7}).json()["threshold"] == 7
    assert client.get("/api/v1/stats/tripwires").json()[0]["id"] == made["id"]
    for bad in ({"comparator": "="}, {"for_minutes": 99999},
                {"query": {"metric": "nope"}}, {"query": {"metric": "total_tokens", "operation": "timeline"}},
                {"name": ""}, {"extra": 1}):
        assert client.post("/api/v1/stats/tripwires", json={**BODY, **bad}).status_code == 422, bad
    with pytest.raises(ValidationError):
        TripwireWrite.model_validate({**BODY, "threshold": float("inf")})
    assert client.delete(f"/api/v1/stats/tripwires/{made['id']}").status_code == 204
    assert client.get(f"/api/v1/stats/tripwires/{made['id']}").status_code == 404
    for _ in range(64):
        _create(client)
    assert client.post("/api/v1/stats/tripwires", json=BODY).status_code == 422
    client.app.dependency_overrides.clear()
    assert client.get("/api/v1/stats/tripwires").status_code == 401


def test_hysteresis_cooldown_unknown_and_single_transition(tmp_path, monkeypatch):
    store, client = _setup(tmp_path)
    box = {"value": 150}
    _feed(monkeypatch, box)
    _create(client)
    t0 = 1_000_000
    assert tripwires.evaluate_all(store, t0) == []
    box["value"] = 50
    assert tripwires.evaluate_all(store, t0 + 120) == []
    assert tripwires.list_tripwires(store)[0]["state"] == "ok"
    box["value"] = 150
    assert tripwires.evaluate_all(store, t0 + 200) == []
    assert tripwires.evaluate_all(store, t0 + 200 + 299) == []
    frames = tripwires.evaluate_all(store, t0 + 200 + 300)
    assert [(f["type"], f["state"], f["value"], f["threshold"]) for f in frames] == [
        ("stats.tripwire", "firing", 150, 100)]
    assert tripwires.evaluate_all(store, t0 + 900) == []
    box["value"] = 50
    assert tripwires.evaluate_all(store, t0 + 1000) == []
    box["value"] = 150
    assert tripwires.evaluate_all(store, t0 + 1100) == []
    box["value"] = 50
    assert tripwires.evaluate_all(store, t0 + 1200) == []
    assert [f["state"] for f in tripwires.evaluate_all(store, t0 + 1500)] == ["ok"]
    box["value"] = 150
    assert tripwires.evaluate_all(store, t0 + 1600) == []
    assert tripwires.evaluate_all(store, t0 + 1900) == []
    assert tripwires.list_tripwires(store)[0]["state"] == "ok"
    assert [f["state"] for f in tripwires.evaluate_all(store, t0 + 200 + 300 + 1800)] == ["firing"]
    box["value"] = None
    assert tripwires.evaluate_all(store, t0 + 5000) == []
    assert tripwires.list_tripwires(store)[0]["state"] == "unknown"
    assert _events(store) == ["tripwire_fired", "tripwire_resolved", "tripwire_fired"]


def test_query_failure_is_unknown_and_disabled_is_skipped(tmp_path, monkeypatch):
    store, client = _setup(tmp_path)
    def boom(store, request):
        raise ValueError("bad")
    monkeypatch.setattr(tripwires.queries, "execute", boom)
    _create(client)
    _create(client, enabled=False)
    assert tripwires.evaluate_all(store, 1_000_000) == []
    assert sorted(t["state"] for t in tripwires.list_tripwires(store)) == ["unknown", "unknown"]
    box = {"value": 1}
    _feed(monkeypatch, box)
    tripwires.evaluate_all(store, 1_000_100)
    assert sorted(t["state"] for t in tripwires.list_tripwires(store) if t["enabled"]) == ["ok"]


def test_deleting_a_chart_deletes_only_its_tripwires(tmp_path):
    from src.api.stats_routes import router as stats_router
    store, client = _setup(tmp_path)
    client.app.include_router(stats_router, prefix="/api/v1")
    chart = {"id": "e8213214-41aa-4fea-8c43-eb5ecb1234d9", "title": "Usage", "enabled": True,
             "series": [{"metric": "total_tokens"}], "filters": {}, "range": {"mode": "global"},
             "display": {"type": "line"}}
    assert client.post("/api/v1/stats/charts", json=chart).status_code == 201
    mine = [_create(client, chart_id=chart["id"]), _create(client, chart_id=chart["id"], name="b")]
    other = _create(client, chart_id="8119ad68-a761-468b-82e2-82827144e4fc", name="c")
    loose = _create(client, name="d")
    assert client.delete(f"/api/v1/stats/charts/{chart['id']}?revision=9").status_code == 409
    assert len(client.get("/api/v1/stats/tripwires").json()) == 4
    assert client.delete(f"/api/v1/stats/charts/{chart['id']}?revision=1").status_code == 204
    left = {t["id"] for t in client.get("/api/v1/stats/tripwires").json()}
    assert left == {other["id"], loose["id"]} and not left & {t["id"] for t in mine}

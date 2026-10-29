from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from src.core.stats import config, queries, tripwires
from src.core.stats.scheduler import StatsScheduler
from src.core.stats.store import StatsStore
from tests.stats import seed
from tests.stats.test_tripwires import _create, _events, _feed, _setup


@pytest.fixture
def store(tmp_path):
    value = StatsStore(tmp_path)
    value.initialize()
    config.ensure_schema(value)
    return value


def test_real_other_value_does_not_collide_with_the_synthetic_series(store):
    ts = 1772949600
    with store.connect() as db:
        for conversation, model, count in (("a", "other", 100), ("b", "B", 20), ("c", "C", 10)):
            seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (ts, "local", "claude", conversation, "p", model, "main",
                          count, 0, 0, 0, 1000, "v1", 1, 1, 0, "ok"))
    request = queries.QueryRequest.model_validate({
        "metric": "total_tokens", "from": "2026-03-08T06:00:00Z", "to": "2026-03-08T08:00:00Z",
        "group_by": "model", "top_n": 2})
    result = queries.execute(store, request)
    keys = [item["key"] for item in result["series"]]
    assert len(keys) == len(set(keys)), keys
    real = next(item for item in result["series"] if item["filter_value"] == "other")
    assert sum(p["value"] or 0 for p in real["points"]) == 100
    fold = next(item for item in result["series"] if item["key"] == "other")
    assert sum(p["value"] or 0 for p in fold["points"]) == 10


def test_one_sqlite_error_answers_that_item_only(store, monkeypatch):
    real = queries._answer_item

    def flaky(view, item, cap, state):
        if item.get("metric") == "cost":
            raise sqlite3.OperationalError("database is locked")
        return real(view, item, cap, state)

    monkeypatch.setattr(queries, "_answer_item", flaky)
    items = [{"metric": "cost", "from": "2026-03-08T06:00:00Z", "to": "2026-03-08T08:00:00Z"},
             {"metric": "total_tokens", "from": "2026-03-08T06:00:00Z", "to": "2026-03-08T08:00:00Z"}]
    results = queries.execute_batch(store, items)["results"]
    assert results[0]["ok"] is False and results[0]["error"]["code"] == "stats_unavailable"
    assert results[1].get("ok", True) is not False


def test_collector_task_survives_a_programming_error(tmp_path, monkeypatch):
    store = StatsStore(tmp_path)
    store.initialize()
    config.ensure_schema(store)
    monkeypatch.setattr(config, "get_settings", lambda s: (_ for _ in ()).throw(TypeError("boom")))
    scheduler = StatsScheduler(store, object(), SimpleNamespace(), tmp_path / "config.json")

    async def exercise():
        task = asyncio.create_task(scheduler._run())
        await asyncio.sleep(0.1)
        assert not task.done()
        assert scheduler.status()["state"] == "error"
        scheduler._cancel.set()
        scheduler._wake.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(exercise())


def test_tripwire_firing_then_unknown_then_clear_still_resolves(tmp_path, monkeypatch):
    store, client = _setup(tmp_path)
    box = {"value": 150}
    _feed(monkeypatch, box)
    _create(client)
    t0 = 1_000_000
    tripwires.evaluate_all(store, t0)
    assert [f["state"] for f in tripwires.evaluate_all(store, t0 + 300)] == ["firing"]
    box["value"] = None
    tripwires.evaluate_all(store, t0 + 400)
    assert tripwires.list_tripwires(store)[0]["state"] == "unknown"
    box["value"] = 50
    tripwires.evaluate_all(store, t0 + 500)
    frames = tripwires.evaluate_all(store, t0 + 800)
    assert [f["state"] for f in frames] == ["ok"]
    assert _events(store) == ["tripwire_fired", "tripwire_resolved"]
    assert tripwires.list_tripwires(store)[0]["state"] == "ok"

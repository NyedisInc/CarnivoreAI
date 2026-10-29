from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.stats_routes import router
from src.api.stats_insight_routes import router as insight_router
from src.api import stats_maintenance_routes  # noqa: F401
from src.models.stats import ChartWrite
from src.core.db_migration import ensure_db_migrated
from src.core.db import db_path_for
from src.core.pipeline import runtime
from src.core.pipeline.engine import Engine
from src.core.stats.plugin.pipeline_plugin import STATS
from src.core.stats import config, reset, wiring
from tests.stats import seed
from src.core.stats.store import StatsStore

CHART = {"id": "e8213214-41aa-4fea-8c43-eb5ecb1234d9", "title": "Usage", "enabled": True,
         "series": [{"metric": "total_tokens"}], "filters": {}, "range": {"mode": "global"},
         "display": {"type": "line"}}


CONV = "7934883d-4a9e-46ca-8516-10788d83b345"


def _line(ts: str, mid: str, tokens: int) -> str:
    return json.dumps({"type": "assistant", "timestamp": ts, "cwd": "/tmp/project", "sessionId": CONV, "message": {
        "id": mid, "model": "claude-sonnet-4-6", "usage": {"input_tokens": tokens, "output_tokens": 2}}}) + "\n"


def _fixture(tmp_path: Path, stamps=None):
    root = tmp_path / "claude"
    source = root / "project" / f"{CONV}.jsonl"
    source.parent.mkdir(parents=True)
    stamps = stamps or [f"2026-09-28T12:0{i}:00Z" for i in range(5)]
    source.write_text("".join(_line(ts, f"m{i}", 10 + i) for i, ts in enumerate(stamps)))
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    store = StatsStore(state)
    wiring.initialize(store)
    return source, store


def _drain(store, source):
    seed.deliver(store.state_dir, source, family="claude", conversation_id=CONV)


def _usage(store):
    with store.connect(readonly=True) as db:
        return [tuple(r) for r in db.execute("SELECT minute_ts,input_tokens,output_tokens,usage_count FROM minute_usage ORDER BY 1")]


def _tables(store):
    with store.connect(readonly=True) as db:
        return {r[0]: db.execute(f'SELECT COUNT(*) FROM "{r[0]}"').fetchone()[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def test_lines_written_while_stats_is_off_are_never_counted(tmp_path):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 1))
    source, store = _fixture(tmp_path, stamps=[now])
    config.update_settings(store, enabled=True, revision=config.get_settings(store)["revision"])
    config.update_settings(store, enabled=False, revision=config.get_settings(store)["revision"])
    _drain(store, source)
    assert _usage(store) == []


def _rebuild_in(monkeypatch, store) -> None:
    monkeypatch.setattr(runtime, "rebuild_plugin", lambda pid: Engine(store.state_dir, db_path=db_path_for(store.state_dir), plugins=(STATS,)).rebuild_plugin(pid))


def test_clear_rebuilds_keeps_settings_and_queues_the_transcripts_again(tmp_path, monkeypatch):
    source, store = _fixture(tmp_path)
    config.update_settings(store, enabled=True, revision=config.get_settings(store)["revision"])
    _drain(store, source)
    with store.connect() as db:
        db.executemany("INSERT INTO stats_events(occurred_at,kind,subject,data) VALUES (?,?,?,?)",
                       [(i, "session_created", "s", "x" * 800) for i in range(4000)])
    config.create_chart(store, ChartWrite.model_validate(CHART))
    assert _usage(store)
    config.update_settings(store, enabled=False, revision=config.get_settings(store)["revision"])
    settings_before = config.get_settings(store)
    _rebuild_in(monkeypatch, store)

    job = reset.clear_stats(store, reset.ClearJob())

    assert _usage(store) == []
    assert _tables(store)["stats_charts"] == 1 and _tables(store)["stats_events"] >= 4000
    assert config.get_settings(store) == settings_before
    public = job.public()
    assert public["state"] == "done" and public["bytes_before"] > 0 and public["bytes_after"] > 0


def test_clear_refuses_while_on_and_without_space(tmp_path):
    _, store = _fixture(tmp_path)
    config.update_settings(store, enabled=True, revision=config.get_settings(store)["revision"])
    try:
        reset.clear_stats(store, reset.ClearJob())
        raise AssertionError("must refuse while on")
    except reset.StatsStillOn:
        pass
    config.update_settings(store, enabled=False, revision=config.get_settings(store)["revision"])
    try:
        reset.clear_stats(store, reset.ClearJob(), free_bytes=lambda _s: 1)
        raise AssertionError("must refuse without space")
    except reset.NotEnoughSpace as exc:
        assert exc.free == 1
    assert store.db_path.exists()


def test_a_redelivery_after_clear_matches_a_fresh_computation(tmp_path, monkeypatch):
    source, store = _fixture(tmp_path)
    config.update_settings(store, enabled=True, revision=config.get_settings(store)["revision"])
    _drain(store, source)
    expected = _usage(store)
    assert expected
    config.update_settings(store, enabled=False, revision=config.get_settings(store)["revision"])
    _rebuild_in(monkeypatch, store)
    reset.clear_stats(store, reset.ClearJob())
    assert _usage(store) == []
    _drain(store, source)
    assert _usage(store) == expected


def _client(tmp_path):
    _, store = _fixture(tmp_path)
    app = FastAPI()
    app.state.stats_store = store
    app.include_router(router, prefix="/api/v1")
    app.include_router(insight_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return app, store


def test_consumers_answer_stats_off_never_zeros(tmp_path):
    app, store = _client(tmp_path)
    item = {"metric": "total_tokens", "from": "2026-09-28T00:00:00Z", "to": "2026-09-29T00:00:00Z"}
    with TestClient(app) as client:
        batch = client.post("/api/v1/stats/query-batch", json={"items": [item]}).json()
        assert batch["results"][0] == {"ok": False, "error": {"code": "stats_off", "message": "stats off"}}
        for res in (client.post("/api/v1/stats/query", json=item),
                    client.get("/api/v1/stats/dimensions", params={"dimension": "model"}),
                    client.get("/api/v1/stats/events", params={"from": "2026-09-28T00:00:00Z", "to": "2026-09-29T00:00:00Z"}),
                    client.get("/api/v1/stats/conversations", params={"from": "2026-09-28T00:00:00Z", "to": "2026-09-29T00:00:00Z"})):
            assert res.status_code == 409 and res.json()["detail"]["code"] == "stats_off"
        settings = client.get("/api/v1/stats/settings").json()
        client.patch("/api/v1/stats/settings", json={"enabled": True, "revision": settings["revision"]})
        assert client.post("/api/v1/stats/query-batch", json={"items": [item]}).json()["results"][0]["ok"] is True


def test_clear_route_needs_confirm_and_off_then_reports_progress(tmp_path, monkeypatch):
    app, store = _client(tmp_path)
    _rebuild_in(monkeypatch, store)
    with TestClient(app) as client:
        assert client.post("/api/v1/stats/clear", json={"confirm": False}).status_code == 422
        settings = client.get("/api/v1/stats/settings").json()
        on = client.patch("/api/v1/stats/settings", json={"enabled": True, "revision": settings["revision"]}).json()
        assert client.post("/api/v1/stats/clear", json={"confirm": True}).json()["detail"]["code"] == "stats_must_be_off"
        client.patch("/api/v1/stats/settings", json={"enabled": False, "revision": on["revision"]})
        assert client.post("/api/v1/stats/clear", json={"confirm": True}).status_code == 202
        for _ in range(100):
            state = client.get("/api/v1/stats/maintenance").json()
            if state["clear"]["state"] in ("done", "failed"):
                break
            time.sleep(0.05)
        assert state["clear"]["state"] == "done" and state["enabled"] is False
        assert state["backfill"]["state"] == "idle" and state["db_bytes"] > 0


def test_maintenance_reads_the_plugins_real_lag_not_a_stored_request_row(tmp_path, monkeypatch):
    from src.core.stats.plugin import progress as progress_mod

    app, store = _client(tmp_path)
    config.ensure_schema(store)
    with store.connect() as db:
        db.execute("INSERT INTO stats_backfill (idempotency_key, state, requested_at, updated_at) VALUES ('stale', 'running', 1, 1)")
    monkeypatch.setattr(progress_mod, "progress", lambda _s: {"known_sources": 10, "pending_sources": 0})
    with TestClient(app) as client:
        assert client.get("/api/v1/stats/maintenance").json()["backfill"]["state"] == "idle"
        monkeypatch.setattr(progress_mod, "progress", lambda _s: {"known_sources": 10, "pending_sources": 3})
        body = client.get("/api/v1/stats/maintenance").json()["backfill"]
        assert body == {"state": "running", "known_sources": 10, "pending_sources": 3}

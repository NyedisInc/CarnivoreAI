from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from datetime import datetime, timezone
from types import SimpleNamespace

from tests.stats import seed
from src.api.auth import require_auth
from src.api.stats_routes import router
from src.core.stats import config
from src.core.stats.store import StatsStore


def _client(tmp_path, *, authenticated=True):
    store = StatsStore(tmp_path)
    store.initialize()
    config.ensure_schema(store)
    with store.connect() as db:
        db.execute("UPDATE stats_settings SET enabled=1")
    app = FastAPI()
    app.state.stats_store = store
    app.include_router(router, prefix="/api/v1")
    if authenticated:
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app)


def test_auth_and_revisioned_chart_round_trip(tmp_path):
    anonymous = _client(tmp_path)
    anonymous.app.dependency_overrides.clear()
    assert anonymous.get("/api/v1/stats/charts").status_code == 401
    client = _client(tmp_path)
    chart = {
        "id": "e8213214-41aa-4fea-8c43-eb5ecb1234d9",
        "title": "Usage", "enabled": True,
        "series": [{"metric": "total_tokens"}],
        "filters": {}, "range": {"mode": "global"}, "display": {"type": "line"},
    }
    created = client.post("/api/v1/stats/charts", json=chart)
    assert created.status_code == 201, created.text
    assert created.json()["id"] == chart["id"]
    assert created.json()["revision"] == 1
    assert client.patch(f"/api/v1/stats/charts/{chart['id']}",
                        json={**chart, "title": "Renamed", "revision": 1}).json()["revision"] == 2
    assert client.patch(f"/api/v1/stats/charts/{chart['id']}",
                        json={**chart, "revision": 1}).status_code == 409
    assert client.post("/api/v1/stats/charts", json={**chart, "token": "secret"}).status_code == 422
    assert client.get("/api/v1/stats/charts").json()[0]["title"] == "Renamed"


def test_settings_disabled_gap_and_backfill_gate(tmp_path):
    client = _client(tmp_path)
    original = client.get("/api/v1/stats/settings").json()
    if not original["enabled"]:
        original = client.patch("/api/v1/stats/settings",
                                json={"enabled": True, "revision": original["revision"]}).json()
    patched = client.patch("/api/v1/stats/settings",
                           json={"enabled": False, "revision": original["revision"]})
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert client.patch("/api/v1/stats/settings",
                        json={"enabled": True, "revision": original["revision"]}).status_code == 409
    assert client.post("/api/v1/stats/backfill",
                       json={"idempotency_key": "repeatable-1"}).status_code == 409
    with client.app.state.stats_store.connect(readonly=True) as db:
        assert db.execute("SELECT COUNT(*) FROM stats_disabled_spans WHERE end_ts IS NULL").fetchone()[0] == 1


def test_same_minute_toggle_keeps_a_nonempty_disabled_span(tmp_path, monkeypatch):
    client = _client(tmp_path)
    monkeypatch.setattr(config, "time", SimpleNamespace(time=lambda: 1800000010))
    setting = client.get("/api/v1/stats/settings").json()
    if not setting["enabled"]:
        setting = client.patch("/api/v1/stats/settings", json={
            "enabled": True, "revision": setting["revision"]}).json()
    off = client.patch("/api/v1/stats/settings", json={
        "enabled": False, "revision": setting["revision"]}).json()
    client.patch("/api/v1/stats/settings", json={"enabled": True, "revision": off["revision"]})
    with client.app.state.stats_store.connect(readonly=True) as db:
        row = db.execute("SELECT start_ts,end_ts FROM stats_disabled_spans ORDER BY start_ts DESC LIMIT 1").fetchone()
    assert row["end_ts"] - row["start_ts"] >= 60


def test_dimension_paging_and_scoped_events(tmp_path):
    client = _client(tmp_path)
    store = client.app.state.stats_store
    with store.connect() as db:
        stamp = int(datetime(2026, 3, 8, 6, tzinfo=timezone.utc).timestamp())
        for model in ("a", "b", "c"):
            seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (stamp, "local", "claude", model, "p", model, "main",
                        1, 0, 0, 0, 10, "v1", 1, 1, 0, "ok"))
    first = client.get("/api/v1/stats/dimensions", params={"dimension": "model", "limit": 2})
    assert first.status_code == 200, first.text
    assert len(first.json()["items"]) == 2
    assert first.json()["next_cursor"] == 2
    assert client.get("/api/v1/stats/dimensions", params={
        "dimension": "model", "limit": 2, "cursor": 2}).json()["items"][0]["filter_value"] == "c"
    for project in ("p", "q"):
        response = client.post("/api/v1/stats/annotations", json={
            "occurred_at": "2026-03-08T06:00:00Z", "kind": "manual",
            "label": project, "scope": {"project": project}})
        assert response.status_code == 201, response.text
    events = client.get("/api/v1/stats/events", params={
        "from": "2026-03-08T00:00:00Z", "to": "2026-03-09T00:00:00Z", "project": "p"})
    assert [item["label"] for item in events.json()["items"]] == ["p"]


def test_analytics_uuid_cells_pass_server_layout_validation():
    from src.core.layouts.shape import validate
    ids = ['analytics:11111111-1111-4111-8111-111111111111',
           'analytics:22222222-2222-4222-8222-222222222222']
    layout = {'v': 7, 'variants': {'wide': {'root': {
        't': 'split', 'id': 's1', 'dir': 'h', 'unit': 'fr', 'sizes': [0.4, 0.6],
        'children': [{'t': 'leaf', 'id': key} for key in ids]}}},
        'hidden': [], 'collapsed': [], 'heroCollapsed': False}
    assert validate({'layout': layout, 'groups': {}})['layout'] == layout


def test_chart_view_settings_round_trip_default_and_validation(tmp_path):
    from pydantic import ValidationError
    from src.models.stats import ChartWrite

    old = {"title": "Usage", "series": [{"metric": "total_tokens"}], "filters": {},
           "range": {"mode": "global"}, "display": {"type": "line"}}
    parsed = ChartWrite.model_validate(old)
    assert parsed.resolution == "auto" and parsed.range.preset is None
    assert parsed.range.zoom is None and parsed.display.hidden_series == []

    client = _client(tmp_path)
    chart = {"id": "9eff1b51-c815-4e4b-87cc-fecc342b2ed3", **old,
             "resolution": "hour", "filters": {"provider": "claude"},
             "range": {"mode": "global", "preset": "7d",
                       "zoom": {"from": "2026-09-20T00:00:00Z", "to": "2026-09-21T00:00:00Z"}},
             "display": {"type": "line", "hidden_series": ["total tokens · codex"]}}
    created = client.post("/api/v1/stats/charts", json=chart)
    assert created.status_code == 201, created.text
    got = client.get(f"/api/v1/stats/charts/{chart['id']}").json()
    assert got["resolution"] == "hour" and got["range"]["preset"] == "7d"
    assert got["range"]["zoom"]["from"].startswith("2026-09-20")
    assert got["display"]["hidden_series"] == ["total tokens · codex"]
    assert got["filters"]["provider"] == "claude" and got["filters"]["project"] is None

    def bad(**patch):
        return client.post("/api/v1/stats/charts", json={**old, **patch}).status_code

    assert bad(resolution="fortnight") == 422
    assert bad(range={"mode": "global", "preset": "3y"}) == 422
    assert bad(range={"mode": "pinned", "from": "2026-09-20T00:00:00Z",
                      "to": "2026-09-21T00:00:00Z", "preset": "1h"}) == 422
    assert bad(range={"mode": "global", "zoom": {"from": "2026-09-21T00:00:00Z",
                                                   "to": "2026-09-20T00:00:00Z"}}) == 422
    assert bad(display={"type": "line", "hidden_series": ["x"] * 33}) == 422
    assert bad(display={"type": "line", "hidden_series": ["y" * 201]}) == 422
    assert bad(display={"type": "line", "hidden_series": ["bad\nname"]}) == 422


def test_viz_options_validation_and_legacy_derive(tmp_path):
    from pydantic import ValidationError
    from src.models.stats import ChartWrite

    base = {"title": "Usage", "series": [{"metric": "total_tokens"}]}
    assert ChartWrite.model_validate(base).viz == "timeline"
    assert ChartWrite.model_validate({**base, "viz": "kpi"}).options == {"compare_prior": True}
    assert ChartWrite.model_validate({**base, "viz": "kpi", "options": {"compare_prior": False}}).options == {"compare_prior": False}
    assert ChartWrite.model_validate({**base, "viz": "leaderboard"}).options == {"top_n": 8}
    assert ChartWrite.model_validate({**base, "viz": "treemap", "options": {"measure": "cost"}}).options == {"measure": "cost"}
    assert ChartWrite.model_validate({**base, "viz": "heat"}).options == {}
    for live_kind in ("vitals", "hot", "events", "fleet", "runway", "swimlanes", "scatter", "health"):
        assert ChartWrite.model_validate({**base, "viz": live_kind}).options == {}
    assert ChartWrite.model_validate({**base, "viz": "flow"}).options == {"measure": "tokens"}
    assert ChartWrite.model_validate({**base, "viz": "impact"}).options == {
        "annotation_id": "", "metric": "estimated_cost_nano_usd", "days": 7}
    for bad in ({"viz": "gauge"}, {"viz": "leaderboard", "options": {"top_n": 11}}, {"viz": "treemap", "options": {"measure": "x"}},
                {"viz": "heat", "options": {"top_n": 3}}, {"viz": "vitals", "options": {"top_n": 3}}, {"viz": "hot", "options": {"nope": 1}}, {"viz": "fleet", "options": {"nope": 1}}, {"viz": "runway", "options": {"top_n": 3}}, {"viz": "swimlanes", "options": {"nope": 1}}, {"viz": "kpi", "options": {"nope": 1}}, {"viz": "timeline", "options": {"compare_prior": True}},
                {"viz": "kpi", "options": {"compare_prior": "maybe"}},
                {"viz": "flow", "options": {"measure": "x"}}, {"viz": "scatter", "options": {"nope": 1}}, {"viz": "health", "options": {"nope": 1}},
                {"viz": "impact", "options": {"days": 31}}, {"viz": "impact", "options": {"metric": "working_seconds"}},
                {"viz": "impact", "options": {"annotation_id": "../etc"}}):
        try:
            ChartWrite.model_validate({**base, **bad})
        except ValidationError:
            continue
        raise AssertionError(f"accepted {bad}")

    client = _client(tmp_path)
    cid = "aceeea12-fd87-4093-821f-e66dc998d10e"
    assert client.post("/api/v1/stats/charts", json={**base, "id": cid, "viz": "kpi"}).status_code == 201
    assert client.get(f"/api/v1/stats/charts/{cid}").json()["viz"] == "kpi"
    assert client.post("/api/v1/stats/charts", json={**base, "viz": "kpi", "options": {"x": 1}}).status_code == 422
    import json as _json
    from src.core.stats.store import StatsStore
    store = StatsStore(tmp_path)
    legacy = {k: v for k, v in _json.loads(_json.dumps(client.get(f"/api/v1/stats/charts/{cid}").json())).items()
              if k not in ("id", "revision", "created_at", "updated_at", "viz", "options")}
    with store.connect() as db:
        db.execute("INSERT INTO stats_charts VALUES (?,?,?,?,?)", ("6fdf75c1-27f6-4636-8afb-26082fa82bb5", 1, _json.dumps(legacy), 1, 1))
    got = client.get("/api/v1/stats/charts/6fdf75c1-27f6-4636-8afb-26082fa82bb5").json()
    assert got["viz"] == "timeline" and got["options"] == {}


def test_legend_on_migration_runs_once(tmp_path):
    import json as _json
    from src.core.stats.store import StatsStore

    store = StatsStore(tmp_path)
    store.initialize()
    config.ensure_schema(store)
    cfg = lambda legend: _json.dumps({"title": "t", "enabled": True, "series": [{"metric": "total_tokens"}], "filters": {},
                                      "range": {"mode": "global"}, "display": {"type": "line", "legend": legend}})
    with store.connect() as db:
        db.execute("DELETE FROM stats_meta WHERE key=?", (config.LEGEND_MIGRATION_KEY,))
        db.execute("INSERT INTO stats_charts VALUES ('off',1,?,1,1)", (cfg(False),))
        db.execute("INSERT INTO stats_charts VALUES ('on',1,?,1,1)", (cfg(True),))
    config.ensure_schema(store)
    assert config.get_chart(store, "off")["display"]["legend"] is True
    assert config.get_chart(store, "off")["revision"] == 2
    assert config.get_chart(store, "on")["revision"] == 1
    with store.connect() as db:
        db.execute("UPDATE stats_charts SET config_json=? WHERE id='off'", (cfg(False),))
    config.ensure_schema(store)
    assert config.get_chart(store, "off")["display"]["legend"] is False
    assert config.get_chart(store, "off")["revision"] == 2


from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.api import ai_routes, beast_mode_routes, stats_event_routes, transcript_manifest_routes
from tests.python.route_tests.harness import client_for, point_state_at


def test_ai_presets_lists_provider_presets_as_data() -> None:
    body = client_for(ai_routes.router, prefix="/api/v1").get("/api/v1/ai/presets").json()
    assert isinstance(body["presets"], list) and body["presets"]
    assert all(isinstance(p, dict) for p in body["presets"])


def test_beast_rules_answers_the_grid_shape() -> None:
    body = client_for(beast_mode_routes.router).get("/beast-mode/rules").json()
    assert {"rows", "cells", "trust_scope", "trust_scopes"} <= set(body)
    assert body["rows"] and {"id", "kind"} <= set(body["rows"][0])


def _stats_client(store: object | None = None):
    client = client_for(stats_event_routes.router)
    if store is not None:
        client.app.state.stats_store = store
    return client


def _range(hours_back: int = 2) -> dict:
    now = datetime.now(timezone.utc)
    return {"from": (now - timedelta(hours=hours_back)).isoformat(), "to": now.isoformat()}


def test_event_log_refuses_a_naive_or_backwards_range() -> None:
    client = _stats_client(object())
    naive = client.get("/stats/event-log", params={"from": "2026-01-01T00:00:00", "to": "2026-01-02T00:00:00"})
    assert naive.status_code == 422 and naive.json()["detail"]["code"] == "invalid_range"
    now = datetime.now(timezone.utc).isoformat()
    assert client.get("/stats/event-log", params={"from": now, "to": now}).status_code == 422


def test_event_log_without_a_stats_store_is_503() -> None:
    resp = _stats_client().get("/stats/event-log", params=_range())
    assert resp.status_code == 503 and resp.json()["detail"]["code"] == "stats_unavailable"


def test_event_log_while_stats_are_off_is_409(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.stats import config

    def off(store: object) -> None:
        raise config.StatsOff()

    monkeypatch.setattr(config, "require_enabled", off)
    resp = _stats_client(object()).get("/stats/event-log", params=_range())
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "stats_off"


def test_event_log_limit_is_bounded() -> None:
    assert _stats_client(object()).get("/stats/event-log", params={**_range(), "limit": 500}).status_code == 422


def test_manifest_on_an_empty_datastore_answers_a_summary_and_no_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    point_state_at(tmp_path, monkeypatch)
    body = client_for(transcript_manifest_routes.router).get("/transcripts/manifest").json()
    assert body["files"] == [] and body["limit"] > 0 and body["offset"] == 0
    assert "summary" in body and "last_scan" in body


@pytest.mark.parametrize("query", [{"status": "bogus"}, {"kind": "bogus"}, {"family": "bogus"}])
def test_manifest_refuses_an_unknown_filter_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, query: dict) -> None:
    point_state_at(tmp_path, monkeypatch)
    resp = client_for(transcript_manifest_routes.router).get("/transcripts/manifest", params=query)
    assert resp.status_code == 422 and next(iter(query)) in resp.json()["detail"]


def test_these_reads_need_auth() -> None:
    for router, url in (
        (ai_routes.router, "/ai/presets"),
        (beast_mode_routes.router, "/beast-mode/rules"),
        (stats_event_routes.router, "/stats/event-log"),
        (transcript_manifest_routes.router, "/transcripts/manifest"),
    ):
        assert client_for(router, signed_in=False).get(url).status_code in (401, 403), url

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.stats_routes import router
from src.cplugs.host import runtime, state as owner_state
from src.core.stats import config
from tests.stats import seed
from tests.stats.test_clear_and_off import CONV, _fixture, _line, _usage

QUERY = {"metric": "total_tokens", "from": "2026-09-28T00:00:00Z", "to": "2026-09-29T00:00:00Z"}


def _app(store) -> FastAPI:
    app = FastAPI()
    app.state.stats_store = store
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return app


def _set(client: TestClient, enabled: bool) -> dict:
    revision = client.get("/api/v1/stats/settings").json()["revision"]
    res = client.patch("/api/v1/stats/settings", json={"enabled": enabled, "revision": revision})
    assert res.status_code == 200
    return res.json()


def _deliver(tmp_path: Path, store, n: int) -> None:
    conv = f"c0ffee00-0000-4000-8000-00000000010{n}"
    source = tmp_path / "claude" / "project" / f"{conv}.jsonl"
    source.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 120 * n))
    source.write_text(_line(stamp, f"m{n}", 100 * n).replace(CONV, conv))
    seed.deliver(store.state_dir, source, family="claude", conversation_id=conv)


def _counted(store) -> int:
    return sum(row[3] for row in _usage(store))


def test_the_core_switch_alone_starts_and_stops_collection_and_readers(tmp_path):
    _, store = _fixture(tmp_path)
    with TestClient(_app(store)) as client:
        assert _set(client, True)["enabled"] is True
        _deliver(tmp_path, store, 1)
        assert _counted(store) == 1
        assert client.post("/api/v1/stats/query", json=QUERY).status_code == 200
        config.require_enabled(store)

        assert _set(client, False)["enabled"] is False
        _deliver(tmp_path, store, 2)
        assert _counted(store) == 1
        res = client.post("/api/v1/stats/query", json=QUERY)
        assert res.status_code == 409 and res.json()["detail"]["code"] == "stats_off"
        with pytest.raises(config.StatsOff):
            config.require_enabled(store)

        assert _set(client, True)["enabled"] is True
        _deliver(tmp_path, store, 3)
        assert _counted(store) == 2


def test_a_new_install_collects_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOUDE_TEST_MODE", raising=False)
    _, store = _fixture(tmp_path)
    assert config.get_settings(store)["enabled"] is True


def test_a_stale_usagestats_plugin_entry_changes_nothing(tmp_path):
    _, store = _fixture(tmp_path)
    config.update_settings(store, enabled=True, revision=config.get_settings(store)["revision"])
    path = owner_state.state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "cplugs": {"usagestats": {"enabled": False, "revision": 3}}}))
    app = _app(store)
    runtime.install(app, Path(tmp_path))
    assert runtime.find("usagestats") is None
    with TestClient(app) as client:
        assert client.get("/api/v1/stats/settings").json()["enabled"] is True

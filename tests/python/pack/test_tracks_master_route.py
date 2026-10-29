
from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import pack_machines_routes
from src.api.auth import require_auth
from src.core.pack.machines import config_state, runtime


def test_tracks_master_defaults_on_stores_and_resyncs_scopes(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text("{}")
    synced: list = []
    wired = SimpleNamespace(state=config_state.ConfigState(lambda: path), sync_scopes=lambda *a: synced.append(a))
    monkeypatch.setattr(runtime, "wiring", lambda: wired)
    app = FastAPI()
    app.include_router(pack_machines_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    client = TestClient(app)

    assert client.get("/api/v1/pack/tracks-master").json() == {"tracks_master": True}
    assert client.put("/api/v1/pack/tracks-master", json={"tracks_master": False}).json() == {"tracks_master": False}
    assert client.get("/api/v1/pack/tracks-master").json() == {"tracks_master": False}
    assert json.loads(path.read_text())["pack_machines"]["tracks_master"] is False
    assert len(synced) == 1
    assert client.put("/api/v1/pack/tracks-master", json={"tracks_master": "no"}).status_code == 422

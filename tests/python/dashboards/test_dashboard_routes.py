
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.dashboard_routes import router as dashboard_router
from src.api.preferences_routes import router as preferences_router
from src.core.ui_preferences_store import UiPreferencesStore


def grid(*slots: str) -> dict:
    return {
        "v": 6,
        "rows": [{"id": "r1", "kind": "px", "size": 120, "slots": [{"id": slot, "fr": 1 / len(slots)} for slot in slots]}],
        "hidden": [],
        "heroCollapsed": False,
        "collapsed": [],
    }


def make_client(tmp_path: Path, monkeypatch, home: dict | None):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {"a": 1}}))
    monkeypatch.setenv("CLOUDE_STATE_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(preferences_router, prefix="/api/v1")
    app.include_router(dashboard_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.ui_preferences_store = UiPreferencesStore(lambda: path)
    app.state.connection_manager = None
    client = TestClient(app)
    if home is not None:
        assert client.patch("/api/v1/preferences", json={"changes": {"home_layout": home}}).status_code == 200
    return client


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    with make_client(tmp_path, monkeypatch, {"v": 2, "boards": [{"id": "home", "name": "ops", "layout": grid("projects")}]}) as test_client:
        yield test_client


def stored(client: TestClient) -> dict:
    return client.get("/api/v1/preferences").json()["values"]["home_layout"]


def test_upgrade_reads_as_dashboard_one_active_and_writes_no_active(client):
    listed = client.get("/api/v1/dashboards").json()
    assert listed["dashboards"] == [{"id": "home", "name": "ops"}]
    assert listed["active"] == "home" and listed["synced"] is True
    assert "active" not in stored(client)


def test_create_set_active_delete(client):
    made = client.post("/api/v1/dashboards", json={"name": "  wall  "})
    assert made.status_code == 200, made.text
    new_id = made.json()["created"]
    assert made.json()["active"] == "home"
    assert stored(client)["boards"][1] == {"id": new_id, "name": "wall", "layout": grid("projects")}

    refused = client.delete("/api/v1/dashboards/home")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "dashboard_active"

    activated = client.post(f"/api/v1/dashboards/{new_id}/activate")
    assert activated.status_code == 200 and activated.json()["active"] == new_id
    assert stored(client)["active"] == new_id

    gone = client.delete("/api/v1/dashboards/home")
    assert gone.status_code == 200, gone.text
    assert gone.json()["dashboards"] == [{"id": new_id, "name": "wall"}]
    last = client.delete(f"/api/v1/dashboards/{new_id}")
    assert last.status_code == 409 and last.json()["detail"]["code"] == "dashboard_active"


def test_layout_save_and_rename_touch_only_their_board(client):
    new_id = client.post("/api/v1/dashboards", json={"name": "side", "layout": grid("notes")}).json()["created"]
    assert client.put(f"/api/v1/dashboards/{new_id}/layout", json={"layout": grid("notes", "projects")}).status_code == 200
    assert client.patch(f"/api/v1/dashboards/{new_id}", json={"name": "side two"}).status_code == 200
    boards = stored(client)["boards"]
    assert boards[0]["layout"] == grid("projects")
    assert boards[1]["name"] == "side two" and boards[1]["layout"] == grid("notes", "projects")


def test_unknown_and_unsynced_are_refused(tmp_path: Path, monkeypatch, client):
    assert client.post("/api/v1/dashboards/nope/activate").json()["detail"]["code"] == "dashboard_unknown"
    (tmp_path / "fresh").mkdir()
    with make_client(tmp_path / "fresh", monkeypatch, None) as fresh:
        assert fresh.get("/api/v1/dashboards").json() == {"dashboards": [], "active": None, "revision": 0, "synced": False}
        assert fresh.post("/api/v1/dashboards", json={"name": "x"}).json()["detail"]["code"] == "home_not_synced"


def test_active_must_name_a_board(client):
    home = {**stored(client), "active": "missing"}
    assert client.patch("/api/v1/preferences", json={"changes": {"home_layout": home}}).status_code == 400

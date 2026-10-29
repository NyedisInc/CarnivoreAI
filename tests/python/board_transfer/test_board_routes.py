
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.board_routes import router as board_router
from src.api.preferences_routes import router as preferences_router
from src.core.board_transfer import MAX_BOARD_FILE_BYTES
from src.core.ui_preferences_store import UiPreferencesStore


def grid(*slots: str, size: int = 120) -> dict:
    return {
        "v": 6,
        "rows": [{"id": "r1", "kind": "px", "size": size, "slots": [{"id": slot, "fr": 1 / len(slots)} for slot in slots]}],
        "hidden": [],
        "heroCollapsed": False,
        "collapsed": [],
    }


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {"a": 1}}))
    monkeypatch.setenv("CLOUDE_STATE_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(preferences_router, prefix="/api/v1")
    app.include_router(board_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.ui_preferences_store = UiPreferencesStore(lambda: path)
    app.state.connection_manager = None
    with TestClient(app) as test_client:
        home = {"v": 2, "boards": [{"id": "home", "name": "ops", "layout": grid("stat-running", "projects")}]}
        assert test_client.patch("/api/v1/preferences", json={"changes": {"home_layout": home}}).status_code == 200
        yield test_client


def boards(client: TestClient) -> list:
    return client.get("/api/v1/preferences").json()["values"]["home_layout"]["boards"]


def test_export_then_import_adds_an_equal_board(client):
    exported = client.get("/api/v1/boards/home/export")
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    document = exported.json()
    assert document["format"] == "carnivore-board" and document["version"] == 1
    preview = client.post("/api/v1/boards/import", json={"document": document, "dry_run": True})
    assert preview.json()["preview"]["ok"] is True
    assert len(boards(client)) == 1
    done = client.post("/api/v1/boards/import", json={"document": document})
    assert done.status_code == 200, done.text
    stored = boards(client)
    assert [board["id"] for board in stored][0] == "home"
    assert stored[1]["id"] == done.json()["board_id"] and stored[1]["name"] == "ops"
    assert stored[1]["layout"] == stored[0]["layout"]


def test_a_board_naming_an_unknown_widget_is_refused_and_any_place_is_not(client):
    document = client.get("/api/v1/boards/home/export").json()
    document["board"]["layout"] = grid("stat-ledger", "no-such-widget", size=400)
    document["drawer_zone"] = {"v": 1, "items": [{"widget": "core.notes"}]}
    refused = client.post("/api/v1/boards/import", json={"document": document})
    assert refused.status_code == 400
    body = refused.json()["detail"]
    assert body["code"] == "board_refused"
    assert body["refusals"] == ["core.no-such-widget is not a widget this install has"]
    assert len(boards(client)) == 1
    document["board"]["layout"] = grid("projects")
    assert client.post("/api/v1/boards/import", json={"document": document}).status_code == 200


def test_the_retired_strip_is_accepted_for_the_browser_to_replace(client):
    document = client.get("/api/v1/boards/home/export").json()
    document["board"]["layout"] = grid("stats", "projects")
    assert client.post("/api/v1/boards/import", json={"document": document, "dry_run": True}).json()["preview"]["ok"]


@pytest.mark.parametrize(
    "mutate, words",
    [
        (lambda d: d.update(format="something-else"), "not a carnivore board file"),
        (lambda d: d.update(version=2), "version 2"),
        (lambda d: d.update(extra=1), "unknown field"),
        (lambda d: d["board"].update(layout={"v": 6, "rows": []}), "not a layout"),
        (lambda d: d.update(settings={"core.notes": {"api_key": "x"}}), None),
    ],
)
def test_an_untrusted_file_is_refused_by_name(client, mutate, words):
    document = client.get("/api/v1/boards/home/export").json()
    mutate(document)
    refused = client.post("/api/v1/boards/import", json={"document": document})
    assert refused.status_code == 400
    detail = refused.json()["detail"]
    text = json.dumps(detail)
    assert (words or "secret") in text
    assert len(boards(client)) == 1


def test_an_oversized_file_is_refused_before_it_is_read(client):
    document = client.get("/api/v1/boards/home/export").json()
    document["board"]["name"] = "x" * 10
    document["settings"] = {"core.notes": {"text": "y" * (MAX_BOARD_FILE_BYTES + 1)}}
    refused = client.post("/api/v1/boards/import", json={"document": document})
    assert refused.status_code == 400
    assert "at most" in refused.json()["detail"]["detail"]


def test_an_unknown_board_export_is_404(client):
    assert client.get("/api/v1/boards/nope/export").status_code == 404


def test_import_applies_widget_settings_and_lists_each_refusal(tmp_path, monkeypatch):
    from contextlib import closing

    from src.config import settings as app_settings
    from src.core import item_settings_store, session_change_notice
    from src.core.db import connect
    from tests.layouts_helpers import migrated

    state_dir = tmp_path / "state"
    db_path = migrated(state_dir)
    monkeypatch.setattr(type(app_settings), "get_state_dir", lambda self: state_dir, raising=True)
    monkeypatch.setattr(session_change_notice, "publish", lambda state, frame: None)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {"a": 1}}))
    app = FastAPI()
    app.include_router(preferences_router, prefix="/api/v1")
    app.include_router(board_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.ui_preferences_store = UiPreferencesStore(lambda: path)
    app.state.connection_manager = None
    with TestClient(app) as http:
        home = {"v": 2, "boards": [{"id": "home", "name": "ops", "layout": grid("stat-running", "projects")}]}
        assert http.patch("/api/v1/preferences", json={"changes": {"home_layout": home}}).status_code == 200
        document = http.get("/api/v1/boards/home/export").json()
        document["settings"] = {"core.activity-log": {"showSystem": False}, "projects": {"nope": 1}}
        done = http.post("/api/v1/boards/import", json={"document": document})
        assert done.status_code == 200, done.text
        body = done.json()
        assert body["settings_applied"] == ["core.activity-log"]
        assert len(body["settings_refused"]) == 1 and "projects" in body["settings_refused"][0]
    with closing(connect(db_path, create=False)) as conn:
        assert item_settings_store.read_item(conn, "widget", "core.activity-log").values == {"showSystem": False}

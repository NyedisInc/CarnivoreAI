
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from tests.python.bookmarks import fixtures


@pytest.fixture
def client(env) -> TestClient:
    from src.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app)


def test_the_widget_read_by_row_id_answers_through_the_aggregator(client):
    resp = client.get("/api/v1/sessions/7/timeline")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_row_id"] == 7 and body["current_conversation"] == fixtures.SOURCE
    assert body["bars"] and body["bars"][-1]["current"]


def test_a_wrapper_agent_row_and_its_uuid_both_read(tmp_path, monkeypatch, client):
    from src.core.bookmarks import rows

    db = fixtures.make_datastore(tmp_path / "wrapped.db", agent_type="claude-chrome", session_uuid="row-uuid-43")
    monkeypatch.setattr(rows, "db_path", lambda: db)
    for key in ("7", "row-uuid-43"):
        resp = client.get(f"/api/v1/sessions/{key}/timeline")
        assert resp.status_code == 200, (key, resp.text)
        assert resp.json()["session_row_id"] == 7


def test_an_unknown_session_is_the_routes_own_404_not_a_missing_route(client):
    resp = client.get("/api/v1/sessions/999/timeline")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "session_not_found"

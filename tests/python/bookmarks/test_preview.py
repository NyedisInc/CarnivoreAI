
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import session_bookmark_routes
from src.api.auth import require_auth
from src.core import item_settings_store
from src.core.bookmarks import preview, store
from src.core.item_settings_ddl import DDL_ITEM_SETTINGS
from tests.python.bookmarks.test_store_routes_mcp import env  # noqa: F401


@pytest.fixture
def client(env):  # noqa: F811
    app = FastAPI()
    app.include_router(session_bookmark_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: "owner"
    app.state.session_manager = SimpleNamespace()
    return TestClient(app)


def _mark(entry_uuid: str) -> int:
    return store.get_store().add(session_uuid="row-uuid-1", session_row_id=7,
                                 claude_session_uuid="11111111-1111-4111-8111-111111111111",
                                 entry_uuid=entry_uuid, label="", created_by="owner").id


def _roles_and_text(body: dict) -> list:
    return [(p["role"], p["text"]) for p in body["parts"]]


def test_preview_returns_the_last_n_messages_oldest_first(client):  # noqa: F811
    mark = _mark("a5")
    two = client.get(f"/api/v1/bookmarks/{mark}/preview?turns=2").json()
    assert two["turns"] == 2
    assert _roles_and_text(two) == [("user", "third prompt"), ("assistant", "done three")]
    four = client.get(f"/api/v1/bookmarks/{mark}/preview?turns=4").json()
    assert _roles_and_text(four) == [("user", "second prompt"), ("assistant", "done two"),
                                     ("user", "third prompt"), ("assistant", "done three")]


def test_preview_joins_a_reply_split_over_records_and_skips_tool_calls(client):  # noqa: F811
    mark = _mark("a2")
    body = client.get(f"/api/v1/bookmarks/{mark}/preview?turns=5").json()
    assert _roles_and_text(body) == [("user", "first prompt"), ("assistant", "looking"), ("assistant", "done one")]


def test_preview_stops_at_the_marked_point_not_the_leaf(client):  # noqa: F811
    mark = _mark("u2")
    body = client.get(f"/api/v1/bookmarks/{mark}/preview?turns=3").json()
    assert _roles_and_text(body)[-1] == ("user", "second prompt")
    assert "third prompt" not in [p["text"] for p in body["parts"]]


def test_n_defaults_to_the_declared_setting_and_follows_a_stored_choice(client, env):  # noqa: F811
    mark = _mark("a5")
    assert client.get(f"/api/v1/bookmarks/{mark}/preview").json()["turns"] == 4
    conn = sqlite3.connect(env["db"])
    conn.executescript(DDL_ITEM_SETTINGS)
    item_settings_store.write_item(conn, "widget", preview.SETTINGS_WIDGET_ID, values={preview.SETTINGS_KEY: 2})
    conn.close()
    body = client.get(f"/api/v1/bookmarks/{mark}/preview").json()
    assert body["turns"] == 2 and len(body["parts"]) == 2


def test_preview_refuses_bad_n_and_missing_things(client, env, monkeypatch):  # noqa: F811
    mark = _mark("a5")
    assert client.get(f"/api/v1/bookmarks/{mark}/preview?turns=0").status_code == 422
    assert client.get(f"/api/v1/bookmarks/{mark}/preview?turns={preview.MAX_PREVIEW_TURNS + 1}").status_code == 422
    assert client.get("/api/v1/bookmarks/999/preview").status_code == 404
    gone = _mark("no-such-record")
    assert client.get(f"/api/v1/bookmarks/{gone}/preview").status_code == 404
    monkeypatch.setattr(preview.locate, "_roots", lambda: (env["tmp"] / "empty",))
    assert client.get(f"/api/v1/bookmarks/{mark}/preview").status_code == 409


def test_long_messages_are_cut_and_flagged(tmp_path):
    from tests.python.bookmarks import fixtures

    path = fixtures.write_transcript(tmp_path / "p")
    text = path.read_text().replace("done three", "x" * (preview.PART_CHARS + 50))
    path.write_text(text)
    parts = preview.preview_parts(path, "a5", 1)
    assert len(parts[0]["text"]) == preview.PART_CHARS and parts[0]["truncated"] is True

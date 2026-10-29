
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import session_bookmark_routes
from src.api.auth import require_auth
from src.config import settings
from src.core import resource_push
from src.core.bookmarks import locate, service, store
from src.core.bookmarks.errors import TranscriptUnavailable
from src.core.resource_push import topics
from tests.python.bookmarks import fixtures
from tests.python.bookmarks.test_store_routes_mcp import env  # noqa: F401


@pytest.fixture
def client(env):  # noqa: F811
    app = FastAPI()
    app.include_router(session_bookmark_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: "owner"
    app.state.session_manager = SimpleNamespace()
    return TestClient(app)


def test_list_all_is_newest_first_across_sessions_with_names_and_every_writer_notifies(client, env, monkeypatch):  # noqa: F811
    sent = []
    monkeypatch.setattr(resource_push, "notify", lambda topic: sent.append(topic))
    first = client.post("/api/v1/sessions/row-uuid-1/bookmarks", json={"label": "one"}).json()
    conn = sqlite3.connect(env["db"])
    conn.execute("INSERT INTO sessions (id, session_uuid, claude_session_uuid, working_dir, title, tmux_name, "
                 "agent_type, host_key) VALUES (8, 'row-uuid-2', 'conv-2', '/x', 'other', 'cloude_other', 'claude', 'local')")
    conn.commit()
    conn.close()
    store.get_store().add(session_uuid="row-uuid-2", session_row_id=8, claude_session_uuid="conv-2", entry_uuid="e",
                          label="two", created_by="claude")
    got = client.get("/api/v1/bookmarks").json()["bookmarks"]
    assert [b["label"] for b in got] == ["two", "one"]
    assert got[0]["session_label"] == "other" and got[0]["family"] == "claude" and got[1]["session_label"] == "api"
    assert client.get("/api/v1/bookmarks?limit=1").json()["bookmarks"][0]["label"] == "two"
    client.delete(f"/api/v1/bookmarks/{first['id']}")
    all_key = topics.keyed(topics.BOOKMARKS, topics.ALL_KEY)
    assert sent.count(all_key) == 3
    assert topics.keyed(topics.BOOKMARKS, "7") in sent


@pytest.fixture
def gone(env, tmp_path, monkeypatch):  # noqa: F811
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    root = tmp_path / "projects"
    return {"state": state, "root": root, "source": locate.find_transcript(fixtures.SOURCE, fixtures.CWD, roots=(root,))}


def test_a_transcript_gone_from_disk_refuses_by_name_and_writes_nothing(gone):
    gone["source"].unlink()
    with pytest.raises(TranscriptUnavailable, match="not on this computer") as caught:
        service.cut_copy(fixtures.SOURCE, "u1", fixtures.CWD)
    assert caught.value.status == 409
    assert not list(gone["root"].rglob("*.jsonl"))

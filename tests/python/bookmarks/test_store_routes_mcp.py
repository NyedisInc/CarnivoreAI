
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_bm_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_bm_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import session_bookmark_routes
from src.api.auth import require_auth
from src.core.bookmarks import locate, rows, store
from src.core.bookmarks.errors import BookmarkNotFound
from src.core.mcp import bookmark_tools, tools
from src.core.mcp.caller import AgentCaller
from tests.python.bookmarks import fixtures


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    fixtures.write_transcript(root)
    db = fixtures.make_datastore(tmp_path / "cloude.db")
    codex_db = fixtures.make_datastore(tmp_path / "codex.db", agent_type="codex", session_uuid="row-codex")
    monkeypatch.setattr(rows, "db_path", lambda: db)
    monkeypatch.setattr(locate, "_roots", lambda: (root,))
    monkeypatch.setattr(rows, "family_of", lambda agent_type: "codex" if agent_type == "codex" else "claude")
    store.set_store(store.BookmarkStore(tmp_path / "bookmarks.db"))
    yield {"db": db, "codex_db": codex_db, "tmp": tmp_path}
    store.set_store(None)


def test_store_round_trip_and_creator_check(tmp_path):
    s = store.BookmarkStore(tmp_path / "b.db")
    first = s.add(session_uuid="r", session_row_id=1, claude_session_uuid="c", entry_uuid="e1", label="  one ",
                  created_by="owner")
    second = s.add(session_uuid="r", session_row_id=1, claude_session_uuid="c", entry_uuid="e2", label="two",
                   created_by="claude")
    assert first.label == "one" and [b.id for b in s.list_for_session("r")] == [second.id, first.id]
    assert s.get(first.id).entry_uuid == "e1" and s.list_for_session("other") == []
    with pytest.raises(ValueError):
        s.add(session_uuid="r", session_row_id=1, claude_session_uuid="c", entry_uuid="e", label="", created_by="x")
    s.delete(first.id)
    with pytest.raises(BookmarkNotFound):
        s.get(first.id)


@pytest.fixture
def client(env):
    app = FastAPI()
    app.include_router(session_bookmark_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: "owner"
    app.state.session_manager = SimpleNamespace()
    return TestClient(app)


def test_routes_add_list_turns_delete_and_refuse(client, env, monkeypatch):
    base = "/api/v1/sessions/row-uuid-1"
    made = client.post(f"{base}/bookmarks", json={"label": "now"})
    assert made.status_code == 201 and made.json()["entry_uuid"] == "u3" and made.json()["snippet"] == "third prompt"
    picked = client.post(f"{base}/bookmarks", json={"entry_uuid": "u1"}).json()
    listed = client.get(f"{base}/bookmarks").json()
    assert [b["id"] for b in listed["bookmarks"]] == [picked["id"], made.json()["id"]]
    assert listed["conversation"] == fixtures.SOURCE and listed["family"] == "claude"
    turns = client.get(f"{base}/turns?limit=2").json()
    assert turns["total"] == 3 and [t["entry_uuid"] for t in turns["turns"]] == ["u3", "u2"]
    assert [t["number"] for t in turns["turns"]] == [3, 2]
    assert client.post(f"{base}/bookmarks", json={"entry_uuid": "side1"}).status_code == 404
    assert client.delete(f"/api/v1/bookmarks/{picked['id']}").status_code == 200
    refused = client.post(f"/api/v1/bookmarks/{made.json()['id']}/rewind", json={})
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "confirm_required"
    monkeypatch.setattr(rows, "db_path", lambda: env["codex_db"])
    codex = client.post("/api/v1/sessions/row-codex/bookmarks", json={})
    assert codex.status_code == 409 and codex.json()["detail"]["code"] == "not_claude"


def test_branch_route_opens_a_new_session_on_the_copy(client, env, monkeypatch):
    created = {}

    async def create_session(**kwargs):
        created.update(kwargs)
        return SimpleNamespace(tmux_session="cloude_api_branch_", model_dump=lambda: {"id": "ses_new"})

    client.app.state.session_manager = SimpleNamespace(create_session=create_session, tmux_socket_name=lambda: "t")
    monkeypatch.setattr("src.core.session_fork.stamp_fork_child", lambda *a, **k: True)
    monkeypatch.setattr(session_bookmark_routes, "_preflight", lambda row: None)
    made = client.post("/api/v1/sessions/row-uuid-1/branch", json={"entry_uuid": "u1"})
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["label"] == "api(branch)" and body["lineage_recorded"] and body["parent_session_id"] == 7
    assert created["agent_extra_args"] == ["--resume", body["claude_session_uuid"]]
    assert fixtures.row_conversation(env["db"])[0] == fixtures.SOURCE


def test_mcp_bookmark_add_marks_the_newest_point_as_claude(env, monkeypatch):
    info = SimpleNamespace(session=SimpleNamespace(id="ses_1"), tmux_session="cloude_fixture", session_row_id=7,
                           host_key="local")

    class View:
        app = None

        async def list_session_infos(self):
            return [info]

    monkeypatch.setattr(bookmark_tools, "_session_uuid_of_row", lambda row_id: "row-uuid-1")
    caller = AgentCaller("ses_1", "cloude_fixture", "ses_1")
    result = asyncio.run(tools.call_tool(View(), caller, "bookmark_add", {"target": "ses_1", "label": "before rm"}))
    assert not result.get("isError"), result
    made = json.loads(result["content"][0]["text"])
    assert (made["created_by"], made["entry_uuid"], made["label"]) == ("claude", "a5", "before rm")
    assert "bookmark_add" in tools.WRITE_TOOLS and "bookmarks_list" not in tools.WRITE_TOOLS

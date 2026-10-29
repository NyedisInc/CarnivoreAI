
from __future__ import annotations

import os
from contextlib import closing
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import session_conversations_routes as routes
from src.api.auth import require_auth
from src.core.db import connect, db_path_for, transaction
from src.core.db_models import SESSION_ORIGIN_ADOPTED
from src.core.session_claude_correlate_bind import bind_correlated_uuid
from src.core.session_identity import record_instance
from tests.s7_helpers import TEST_SOCKET, migrated_connection, session_row

from .helpers import A_ID, B_ID, C_ID, WORKING_DIR, command_lines, normal_lines, write_transcript

NAME = "cloude_lineage_api"


class Manager:

    def __init__(self):
        self.created = []

    def tmux_socket_name(self):
        return TEST_SOCKET

    async def create_session(self, **kw):
        self.created.append(kw)
        return SimpleNamespace(tmux_session="cloude_child", model_dump=lambda: {"id": kw["session_id"]})


@pytest.fixture()
def world(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    corpus = tmp_path / "projects"
    corpus.mkdir()
    with closing(migrated_connection(state)) as conn:
        with transaction(conn):
            record_instance(conn, socket=TEST_SOCKET, name=NAME, epoch=1_800_000_000, origin=SESSION_ORIGIN_ADOPTED,
                            working_dir=WORKING_DIR)
            bind_correlated_uuid(conn, socket=TEST_SOCKET, name=NAME, epoch=1_800_000_000, claude_uuid=B_ID)
            uuid = session_row(conn, NAME)["session_uuid"]
            conn.execute("INSERT INTO conversation_index (conversation_id, session_uuid, ended_reason, ended_at, first_prompt, "
                         "summary, captured_at, updated_at) VALUES (?, ?, 'clear', '2026-09-29T12:00:00Z', 'the old task', "
                         "'it fixed the parser', 't', 't')", (A_ID, uuid))
            conn.execute("INSERT INTO lineage_edges (parent_type, parent_id, child_type, child_id, edge_kind, created_at) "
                         "VALUES ('conversation', ?, 'session', ?, 'clear', '2026-09-29T12:00:00Z')", (A_ID, uuid))
    write_transcript(corpus, A_ID, normal_lines("the old task"))
    write_transcript(corpus, B_ID, command_lines("/clear"))
    monkeypatch.setattr(routes, "_db_path", lambda: db_path_for(state))
    monkeypatch.setattr(routes, "_corpus_root", lambda: corpus)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    manager = Manager()
    app.state.session_manager = manager
    return SimpleNamespace(client=TestClient(app), app=app, uuid=uuid, manager=manager, corpus=corpus)


def test_every_route_requires_auth(world):
    world.app.dependency_overrides.clear()
    client = TestClient(world.app)
    for method, path in [("get", f"/api/v1/sessions/{world.uuid}/conversations"), ("get", "/api/v1/session-conversations/counts"),
                         ("post", f"/api/v1/sessions/{world.uuid}/conversations/{A_ID}/resume")]:
        assert getattr(client, method)(path).status_code in (401, 403)


def test_list_returns_current_and_previous_newest_first(world):
    body = world.client.get(f"/api/v1/sessions/{world.uuid}/conversations").json()
    assert body["current"]["conversation_id"] == B_ID and body["current"]["current"] is True
    assert body["previous_count"] == 1
    prev = body["previous"][0]
    assert prev["conversation_id"] == A_ID and prev["ended_reason"] == "clear" and prev["first_prompt"] == "the old task"
    assert prev["transcript_on_disk"] is True and prev["summary"] == "it fixed the parser"


def test_previous_without_an_index_row_reads_its_transcript(world):
    mtime = 1_790_000_000.0
    write_transcript(world.corpus, C_ID, normal_lines("port the parser", "2026-09-20T08:00:00Z"), mtime=mtime)
    with closing(connect(db_path_for(world.corpus.parent / "state"), create=False)) as conn:
        with transaction(conn):
            conn.execute("INSERT INTO lineage_edges (parent_type, parent_id, child_type, child_id, edge_kind, created_at) "
                         "VALUES ('conversation', ?, 'session', ?, 'fork', '2026-09-21T00:00:00Z')", (C_ID, world.uuid))
    body = world.client.get(f"/api/v1/sessions/{world.uuid}/conversations").json()
    prev = {p["conversation_id"]: p for p in body["previous"]}[C_ID]
    assert prev["started_at"] == "2026-09-20T08:00:00Z" and prev["first_prompt"] == "port the parser"
    assert prev["ended_at"] == "2026-09-21T14:13:20Z" and prev["summary"] is None


def test_unknown_session_is_404(world):
    assert world.client.get("/api/v1/sessions/nope/conversations").status_code == 404


def test_counts(world):
    assert world.client.get("/api/v1/session-conversations/counts").json() == {"by_session": {world.uuid: 1}}


def test_resume_forks_the_earlier_conversation_into_a_new_session(world):
    resp = world.client.post(f"/api/v1/sessions/{world.uuid}/conversations/{A_ID}/resume")
    assert resp.status_code == 201
    (call,) = world.manager.created
    assert call["agent_extra_args"] == ["--resume", A_ID, "--fork-session"] and call["working_dir"] == WORKING_DIR
    assert resp.json()["parent_session_id"] is not None
    with closing(connect(routes._db_path())) as conn:
        assert session_row(conn, NAME)["claude_session_uuid"] == B_ID


def test_resume_refuses_a_foreign_conversation_and_a_missing_transcript(world):
    assert world.client.post(f"/api/v1/sessions/{world.uuid}/conversations/{'d' * 8}/resume").status_code == 404
    (world.corpus / next(world.corpus.iterdir()).name / f"{A_ID}.jsonl").unlink()
    assert world.client.post(f"/api/v1/sessions/{world.uuid}/conversations/{A_ID}/resume").status_code == 409
    assert world.manager.created == []


def test_listing_carries_no_restore_points_and_the_restore_route_is_gone(world):
    body = world.client.get(f"/api/v1/sessions/{world.uuid}/conversations").json()
    assert "restore_points" not in body["current"] and "restore_points" not in body["previous"][0]
    assert world.client.post(f"/api/v1/sessions/{world.uuid}/conversations/{A_ID}/restore", json={}).status_code == 404

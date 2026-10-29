
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from contextlib import closing

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import session_fork
from src.core.bookmarks import actions, locate, rows
from src.core.db import db_path_for, transaction
from src.core.lineage import constants as K
from src.core.lineage import ddl, events, graph, scan, split
from tests.python.bookmarks import fixtures
from tests.s7_helpers import migrated_connection


class _Child:
    tmux_session = "cloude_fixture_branch"

    def model_dump(self) -> dict:
        return {}


class _Manager:
    def tmux_socket_name(self) -> str:
        return "test_sock"

    async def create_session(self, **kwargs):
        return _Child()


def test_a_bookmark_branch_stores_the_cut_on_the_fork_edges(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    fixtures.write_transcript(root)
    db = fixtures.make_datastore(tmp_path / "cloude.db")
    with closing(sqlite3.connect(db)) as raw:
        for statement in ddl.DDL_V49:
            raw.execute(statement)
        raw.commit()
    monkeypatch.setattr(rows, "db_path", lambda: db)
    monkeypatch.setattr(locate, "_roots", lambda: (root,))
    monkeypatch.setattr(rows, "family_of", lambda agent_type: "claude")
    monkeypatch.setattr(session_fork, "stamp_fork_child", lambda *a, **k: True)
    monkeypatch.setattr(actions, "_child_session_uuid", lambda socket, tmux: "child-session")
    done = asyncio.run(actions.branch(_Manager(), session_uuid="row-uuid-1", entry_uuid="u2"))
    copy = done["claude_session_uuid"]
    assert done["split_recorded"] is True
    with closing(sqlite3.connect(db)) as raw:
        found = {(r[0], r[1], r[2]): json.loads(r[3]) for r in raw.execute(
            "SELECT child_type, child_id, edge_kind, detail_json FROM lineage_edges")}
        marks = raw.execute("SELECT kind, session_uuid FROM conversation_milestones").fetchall()
    assert set(found) == {("conversation", copy, "fork"), ("session", "child-session", "fork")}
    for detail in found.values():
        assert detail[K.DETAIL_SPLIT_SESSION] == fixtures.SOURCE and detail[K.DETAIL_SPLIT_MESSAGE] == "u2"
        assert detail[K.DETAIL_VIA] == K.VIA_BOOKMARK_BRANCH
    assert marks == [("fork", "child-session")]


def _fork_transcript(path, parent="parent-conv", message="m13", at_line=3):
    records = [{"type": "mode"}, {"type": "permission-mode"}]
    records.insert(at_line - 1, {"type": "user", "forkedFrom": {"sessionId": parent, "messageUuid": message},
                                 "message": {"role": "user", "content": "hi"}})
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_the_pointer_reader_returns_conversation_message_and_line(tmp_path):
    path = tmp_path / "child.jsonl"
    _fork_transcript(path)
    assert split.read_split_point(path) == split.SplitPoint("parent-conv", "m13", 3)
    plain = tmp_path / "plain.jsonl"
    plain.write_text(json.dumps({"type": "user"}) + "\n")
    assert split.read_split_point(plain) is None


@pytest.fixture()
def state(tmp_path):
    folder = tmp_path / "state"
    folder.mkdir()
    migrated_connection(folder).close()
    return folder


def test_a_live_fork_flip_gains_its_split_point_from_the_copys_head(state, tmp_path, monkeypatch):
    projects = tmp_path / "projects" / "-proj"
    projects.mkdir(parents=True)
    _fork_transcript(projects / "child-conv.jsonl")
    monkeypatch.setattr(scan, "roots", lambda corpus_root=None: (tmp_path / "projects",))
    db = db_path_for(state)
    assert events.write_capture_event(db, "fork", "parent-conv", "sess-1", child_conversation_id="child-conv",
                                      at_ts="2026-10-10T10:00:00+00:00") == events.EVENT_WRITTEN
    with closing(sqlite3.connect(db)) as raw:
        raw.row_factory = sqlite3.Row
        edges = {(r["child_type"], r["child_id"]): json.loads(r["detail_json"]) for r in raw.execute(
            "SELECT * FROM lineage_edges WHERE edge_kind = 'fork'")}
    assert set(edges) == {("conversation", "child-conv"), ("session", "sess-1")}
    conv = edges[("conversation", "child-conv")]
    assert conv[K.DETAIL_SPLIT_SESSION] == "parent-conv" and conv[K.DETAIL_SPLIT_MESSAGE] == "m13"
    assert conv[K.DETAIL_COPY_LINE] == 3


def test_recording_a_pointer_twice_changes_nothing(state, tmp_path):
    path = tmp_path / "child-conv.jsonl"
    _fork_transcript(path)
    conn = migrated_connection(state)
    try:
        with transaction(conn):
            assert split.record_fork_pointer(conn, "child-conv", path, {"child-conv": "s2"}) is True
        before = conn.execute("SELECT * FROM lineage_edges ORDER BY 1,2,3,4,5").fetchall()
        with transaction(conn):
            split.record_fork_pointer(conn, "child-conv", path, {"child-conv": "s2"})
        assert conn.execute("SELECT * FROM lineage_edges ORDER BY 1,2,3,4,5").fetchall() == before
        assert len(before) == 2 and graph.parents_of(conn, "session", "s2")[0]["edge_kind"] == "fork"
    finally:
        conn.close()

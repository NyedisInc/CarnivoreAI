
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
from src.core import restart_live_gate
from src.core.bookmarks import actions, locate, rows
from src.core.db import transaction
from src.core.lineage import constants as K
from src.core.lineage import ddl, events, graph, milestones, reclassify
from tests.python.bookmarks import fixtures
from tests.s7_helpers import migrated_connection


class _Manager:
    def tmux_socket_name(self) -> str:
        return "test_sock"

    async def respawn_session(self, name: str, **kwargs) -> dict:
        conversation = fixtures.row_conversation(self.db)[0]
        return {"ok": True, "killed_live_pane": True, "kind": "agent", "identity_status": "verified",
                "command": f"claude --resume {conversation}"}


def test_a_rewind_writes_an_edge_a_milestone_and_the_split_point(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    source = fixtures.write_transcript(root)
    db = fixtures.make_datastore(tmp_path / "cloude.db")
    with closing(sqlite3.connect(db)) as raw:
        for statement in ddl.DDL_V49:
            raw.execute(statement)
        raw.commit()
    monkeypatch.setattr(rows, "db_path", lambda: db)
    monkeypatch.setattr(locate, "_roots", lambda: (root,))
    monkeypatch.setattr(rows, "family_of", lambda agent_type: "claude")
    monkeypatch.setattr(restart_live_gate, "bound_instance_running", lambda *a, **k: True)
    manager = _Manager()
    manager.db = db
    done = asyncio.run(actions.rewind(manager, session_uuid="row-uuid-1", entry_uuid="u2", confirm=True))
    copy = done["claude_session_uuid"]
    assert done["lineage_recorded"] is True and source.is_file()
    with closing(sqlite3.connect(db)) as raw:
        found = {(r[0], r[1], r[2]): json.loads(r[3]) for r in raw.execute(
            "SELECT child_type, child_id, edge_kind, detail_json FROM lineage_edges WHERE parent_id = ?",
            (fixtures.SOURCE,))}
        marks = raw.execute("SELECT kind, session_uuid FROM conversation_milestones WHERE conversation_id = ?",
                            (fixtures.SOURCE,)).fetchall()
    assert set(found) == {("conversation", copy, "rewind"), ("session", "row-uuid-1", "rewind")}
    split = found[("conversation", copy, "rewind")]
    assert split[K.DETAIL_SPLIT_SESSION] == fixtures.SOURCE and split[K.DETAIL_SPLIT_MESSAGE] == "u2"
    assert split[K.DETAIL_VIA] == K.VIA_BOOKMARK_REWIND
    assert marks == [("rewind", "row-uuid-1")]


def test_a_rewind_on_a_datastore_before_v49_still_succeeds_and_says_it_recorded_nothing(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    fixtures.write_transcript(root)
    db = fixtures.make_datastore(tmp_path / "cloude.db")
    monkeypatch.setattr(rows, "db_path", lambda: db)
    monkeypatch.setattr(locate, "_roots", lambda: (root,))
    monkeypatch.setattr(rows, "family_of", lambda agent_type: "claude")
    monkeypatch.setattr(restart_live_gate, "bound_instance_running", lambda *a, **k: True)
    manager = _Manager()
    manager.db = db
    done = asyncio.run(actions.rewind(manager, session_uuid="row-uuid-1", entry_uuid="u2", confirm=True))
    assert done["ok"] is True and done["lineage_recorded"] is False


def _write(root, conversation, records):
    folder = root / "-proj"
    folder.mkdir(exist_ok=True)
    (folder / f"{conversation}.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _command(name):
    return {"type": "user", "timestamp": "2026-10-10T10:00:00Z",
            "message": {"role": "user", "content": f"<command-name>{name}</command-name>"}}


@pytest.fixture()
def conn(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    connection = migrated_connection(state)
    yield connection
    connection.close()


def _flip(conn, parent, child, session="s1"):
    with transaction(conn):
        events.record_flip_edges(conn, parent, session, "switch", child_conversation_id=child)
        milestones.add_milestone(conn, parent, "switch", K.SOURCE_PIPELINE, session_uuid=session,
                                 detail={"child_conversation_id": child})


def _kinds(conn):
    return sorted(r[0] for r in conn.execute("SELECT edge_kind FROM lineage_edges"))


def test_a_switch_whose_new_transcript_opens_with_clear_becomes_a_recorded_clear(conn, tmp_path):
    _flip(conn, "old", "new")
    (tmp_path / "root").mkdir()
    _write(tmp_path / "root", "new", [_command("/clear")])
    with transaction(conn):
        assert reclassify.reclassify_switches(conn, roots=[tmp_path / "root"]) == 2
    assert _kinds(conn) == ["clear", "clear"]
    edge = graph.parents_of(conn, "conversation", "new")[0]
    assert edge["link_basis"] == "recorded" and edge["detail"][K.DETAIL_EVIDENCE] == K.EVIDENCE_COMMAND_RECORD
    assert [m["kind"] for m in milestones.milestones_of(conn, "old")] == ["clear"]
    with transaction(conn):
        assert reclassify.reclassify_switches(conn, roots=[tmp_path / "root"]) == 0


def test_a_switch_with_nothing_to_prove_it_stays_a_switch(conn, tmp_path):
    _flip(conn, "old", "new")
    (tmp_path / "root").mkdir()
    _write(tmp_path / "root", "new", [{"type": "user", "message": {"role": "user", "content": "hello"}}])
    with transaction(conn):
        assert reclassify.reclassify_switches(conn, roots=[tmp_path / "root"]) == 0
    assert _kinds(conn) == ["switch", "switch"]


def test_a_forked_from_pointer_turns_a_switch_into_a_fork_with_its_split(conn, tmp_path):
    _flip(conn, "old", "new")
    (tmp_path / "root").mkdir()
    _write(tmp_path / "root", "new", [{"type": "user", "forkedFrom": {"sessionId": "old", "messageUuid": "m9"},
                                       "message": {"role": "user", "content": "hi"}}])
    with transaction(conn):
        reclassify.reclassify_switches(conn, roots=[tmp_path / "root"])
    assert _kinds(conn) == ["fork", "fork"]
    assert graph.parents_of(conn, "conversation", "new")[0]["detail"][K.DETAIL_SPLIT_SESSION] == "old"

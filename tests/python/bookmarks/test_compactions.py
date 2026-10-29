
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing

import pytest

from src.core import resource_push
from src.core.bookmarks import actions, compactions, cut, locate, preview, rows, service, transcript_index
from src.core.bookmarks.errors import EntryNotFound
from src.core.lineage import constants as LK
from src.core.lineage import ddl, milestones
from tests.python.bookmarks import fixtures


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    source = fixtures.write_transcript(root)
    db = fixtures.make_datastore(tmp_path / "cloude.db")
    with closing(sqlite3.connect(db)) as conn:
        for stmt in ddl.DDL_V49:
            conn.execute(stmt)
        conn.commit()
    monkeypatch.setattr(rows, "db_path", lambda: db)
    monkeypatch.setattr(locate, "_roots", lambda: (root,))
    monkeypatch.setattr(rows, "family_of", lambda agent_type: "claude")
    return {"db": db, "source": source}


def _record(db, *, detail, line=19, offset=None, at="2026-10-06T00:00:02Z"):
    with closing(sqlite3.connect(db)) as conn:
        milestones.add_milestone(conn, fixtures.SOURCE, LK.MILESTONE_COMPACT, LK.SOURCE_JSONL_SCAN, at_ts=at,
                                 jsonl_line=line, jsonl_offset=offset, detail=detail)
        conn.commit()


def test_a_recorded_compact_is_a_compaction_point_but_never_a_bookmark(env):
    _record(env["db"], detail={"record_uuid": "cb", "trigger": "manual", "pre_tokens": 90000})
    listed = service.list_bookmarks("row-uuid-1")
    assert listed["bookmarks"] == [] and listed["compactions"] == []
    [point] = compactions.list_compactions(fixtures.SOURCE, fixtures.CWD)
    assert point["entry_uuid"] == "cb" and point["trigger"] == "manual" and point["pre_tokens"] == 90000


def test_an_old_milestone_without_a_uuid_is_resolved_by_its_byte_offset(env):
    index = transcript_index.build_index(env["source"])
    _record(env["db"], detail={}, offset=index.nodes["cb"].offset)
    assert compactions.list_compactions(fixtures.SOURCE, fixtures.CWD)[0]["entry_uuid"] == "cb"


def test_an_unresolvable_point_is_listed_with_no_entry(env):
    _record(env["db"], detail={}, offset=None, line=3)
    assert compactions.list_compactions(fixtures.SOURCE, fixtures.CWD)[0]["entry_uuid"] is None


def test_a_datastore_without_lineage_tables_lists_none(tmp_path, monkeypatch):
    db = fixtures.make_datastore(tmp_path / "cloude.db")
    monkeypatch.setattr(rows, "db_path", lambda: db)
    assert compactions.list_compactions(fixtures.SOURCE) == []


def test_a_cut_at_the_boundary_lands_on_the_summary_and_keeps_the_compacted_state(env):
    index = transcript_index.build_index(env["source"])
    chain = cut.kept_chain(index, "cb")
    assert [n.uuid for n in chain] == ["cb", "cs"]


def test_branch_from_a_compaction_cuts_the_copy_at_its_summary(env, tmp_path):
    new_uuid, path = service.cut_copy(fixtures.SOURCE, "cb", fixtures.CWD)
    kept = [__import__("json").loads(line)["uuid"] for line in path.read_text().splitlines() if '"uuid"' in line]
    assert kept == ["cb", "cs"] and new_uuid != fixtures.SOURCE


def test_rewind_to_a_compaction_swaps_the_row_to_the_cut_copy(env, monkeypatch):
    from src.core import restart_live_gate

    monkeypatch.setattr(restart_live_gate, "bound_instance_running", lambda *a, **k: True)

    class Manager:
        def tmux_socket_name(self):
            return "test_sock"

        async def respawn_session(self, name, **kwargs):
            conversation = fixtures.row_conversation(env["db"])[0]
            return {"ok": True, "killed_live_pane": True, "command": f"claude --resume {conversation}"}

    done = asyncio.run(actions.rewind(Manager(), session_uuid="row-uuid-1", entry_uuid="cb", confirm=True))
    assert done["ok"] and done["resumed_copy"] and done["claude_session_uuid"] != fixtures.SOURCE


def test_a_new_compaction_pushes_the_sessions_bookmark_topic(env, monkeypatch):
    seen = []
    monkeypatch.setattr(resource_push, "notify", lambda topic: seen.append(topic))
    compactions.announce("row-uuid-1")
    compactions.announce("no-such-row")
    assert seen == ["bookmarks:7", "bookmarks:*"]


def test_compaction_preview_shows_the_messages_before_the_boundary(env):
    _record(env["db"], detail={"record_uuid": "cb", "trigger": "manual", "pre_tokens": 1})
    body = preview.compaction_preview("row-uuid-1", "cb", 3)
    assert [(p["role"], p["text"]) for p in body["parts"]] == [
        ("assistant", "done one"), ("user", "second prompt"), ("assistant", "done two")]
    assert body["entry_uuid"] == "cb" and body["turns"] == 3
    assert preview.compaction_preview("row-uuid-1", "cb")["turns"] == 4


def test_compaction_preview_refuses_a_uuid_that_is_not_a_compaction(env):
    _record(env["db"], detail={"record_uuid": "cb"})
    with pytest.raises(EntryNotFound):
        preview.compaction_preview("row-uuid-1", "u2")


def test_compaction_preview_route(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import session_bookmark_routes
    from src.api.auth import require_auth

    _record(env["db"], detail={"record_uuid": "cb"})
    app = FastAPI()
    app.include_router(session_bookmark_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: "owner"
    client = TestClient(app)
    body = client.get("/api/v1/sessions/row-uuid-1/compactions/cb/preview?turns=2").json()
    assert [p["text"] for p in body["parts"]] == ["second prompt", "done two"]
    assert client.get("/api/v1/sessions/row-uuid-1/compactions/u2/preview").status_code == 404


def test_the_all_sessions_list_carries_no_compactions_but_the_batched_read_still_finds_them(env):
    _record(env["db"], detail={"record_uuid": "cb", "trigger": "auto", "pre_tokens": 5})
    assert service.list_all(10)["compactions"] == []
    [point] = compactions.list_all_compactions(10)
    assert (point["entry_uuid"], point["session_row_id"], point["session_label"], point["family"]) == ("cb", 7, "api", "claude")
    assert service.list_all(10)["bookmarks"] == []
    assert compactions.list_all_compactions(0) == []


def test_the_batched_read_leaves_out_a_non_claude_session(env, monkeypatch):
    _record(env["db"], detail={"record_uuid": "cb"})
    monkeypatch.setattr(rows, "family_of", lambda agent_type: "codex")
    assert compactions.list_all_compactions(10) == []

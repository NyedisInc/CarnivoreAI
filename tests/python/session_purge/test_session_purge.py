
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from typing import Any

import pytest
from fastapi import HTTPException

from src.api import session_purge_routes as routes
from src.core.db import connect
from src.core.mcp import pending, session_purge_tools
from src.core.mcp.approvals import typed_confirm
from src.core.mcp.common import ToolError
from tests.python.session_purge import purge_world as W


@pytest.fixture
def world(tmp_path: Any, monkeypatch: Any) -> Any:
    w = W.build(tmp_path, monkeypatch)
    monkeypatch.setattr(routes, "_panes", lambda: (True, ()))
    return w


def plan() -> dict:
    return routes.plan_and_maybe_apply(W.UUID, routes.SessionPurgeRequest(), False)


def apply(fingerprint: str, typed: str | None = W.TITLE, beast: bool = True) -> dict:
    body = routes.SessionPurgeRequest(apply=True, plan_fingerprint=fingerprint, confirm_text=typed)
    return routes.plan_and_maybe_apply(W.UUID, body, beast)


def rows(w: Any, table: str, where: str, *params: Any) -> int:
    with closing(connect(w.db)) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0])


def by_what(answer: dict) -> dict:
    return {(a["store"], a["what"]): a for a in answer["artifacts"]}


def test_plan_traces_every_kind_and_changes_nothing(world: Any) -> None:
    answer = plan()
    assert answer["ok"] and answer["complete"] and answer["fingerprint"]
    assert answer["confirm_text"] == W.TITLE
    found = by_what(answer)
    for table in ("sessions", "session_notes", "session_group_membership", "conversation_index", "transcript_files",
                  "transcript_archives", "transcript_records"):
        assert found[("cloude.db", table)]["action"] == "delete", table
    for key in ("bookmarks.db", "attention_history.db"):
        assert any(store == key for store, _ in found), key
    assert ("ui_preferences", "drawer_arrangement") in found
    assert ("ui_preferences", f"terminal_layouts[{W.NAME}:{W.EPOCH}]") in found
    assert found[("ui_preferences", f"terminal:row:{world.row} tabs")]["action"] == "report"
    assert ("session-journal", str(world.journal)) in found
    paths = {a["what"] for a in answer["artifacts"] if a["kind"] in ("file", "dir")}
    for key, path in world.files.items():
        expect = path
        if key in ("short_spelling_subagent",):
            expect = path.parent.parent
        elif key in ("file_history", "session_env"):
            expect = path.parent
        assert str(expect) in paths, key
    assert str(world.keep) not in paths
    history = found[("claude", str(world.home / "history.jsonl"))]
    assert history["action"] == "report" and history["count"] == 1
    assert all(p.exists() for p in world.files.values())
    assert rows(world, "sessions", "session_uuid = ?", W.UUID) == 1


def test_apply_removes_everything_and_writes_a_content_free_receipt(world: Any) -> None:
    answer = apply(plan()["fingerprint"])
    done = answer["done"]
    assert done["status"] == "done" and done["failed"] == 0
    assert not any(p.exists() for p in world.files.values())
    assert world.keep.exists() and (world.home / "history.jsonl").exists()
    assert (world.home / "sessions" / "77.json").exists()
    assert rows(world, "sessions", "session_uuid = ?", W.UUID) == 0
    for table, col in (("session_notes", "session_uuid"), ("conversation_index", "conversation_id"),
                       ("transcript_files", "conversation_id"), ("transcript_archives", "claude_session_uuid")):
        assert rows(world, table, f"{col} IN (?, ?)", W.UUID, W.CONV) == 0, table
    with closing(sqlite3.connect(world.state / "bookmarks.db")) as side:
        assert side.execute("SELECT session_uuid FROM bookmarks").fetchall() == [("other",)]
    prefs = json.loads(world.config.read_text())["ui_preferences"]
    values = prefs["values"]
    assert values["drawer_arrangement"]["pinned"] == ["keep-me"] and values["drawer_arrangement"]["order"] == []
    assert values["drawer_arrangement"]["bands"] == {"g:x": ["o"]}
    assert list(values["terminal_layouts"]["sessions"]) == ["other:1"] and prefs["revision"] > 3
    journal = json.loads(world.journal.read_text())
    assert list(journal["sessions"]) == ["k2"]
    receipt = done["receipt"]
    text = open(receipt).read()
    assert "never reach a receipt" not in text
    body = json.loads(text)
    assert body["status"] == "done" and body["session"]["session_uuid"] == W.UUID
    assert all("status" in a for a in body["artifacts"])


def _share(world: Any) -> None:
    with closing(connect(world.db)) as conn:
        W.add_session(conn, "sess-other", "carnivore_other", "99999999-aaaa-bbbb-cccc-000000000001", epoch=5)
        conn.execute("UPDATE conversation_index SET session_uuid = 'sess-other' WHERE conversation_id = ?", (W.CONV,))


def test_shared_transcript_is_kept_and_the_purge_says_incomplete(world: Any) -> None:
    _share(world)
    with closing(connect(world.db)) as conn:
        conn.execute("UPDATE transcript_archives SET root_session_id = NULL")
    answer = plan()
    assert answer["ok"] and not answer["complete"]
    assert answer["shared_with"][0]["session_uuid"] == "sess-other"
    found = by_what(answer)
    kept = found[("claude", str(world.files["transcript"]))]
    assert kept["action"] == "keep" and "shared with" in kept["reason"]
    assert found[("cloude.db", "transcript_files")]["action"] == "keep"
    done = apply(answer["fingerprint"])["done"]
    assert done["status"] == "done"
    assert world.files["transcript"].exists() and world.files["codex"].exists()
    assert rows(world, "sessions", "session_uuid = ?", W.UUID) == 0
    assert rows(world, "transcript_files", "conversation_id = ?", W.CONV) == 1
    assert rows(world, "conversation_index", "session_uuid = ?", "sess-other") == 1


def test_shared_archive_rooted_on_the_row_blocks(world: Any) -> None:
    _share(world)
    answer = plan()
    assert not answer["ok"] and any("rooted on this session row" in b for b in answer["blockers"])


def test_live_session_is_refused(world: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(routes, "_panes", lambda: (True, ((W.NAME, W.EPOCH, "/w/proj"),)))
    answer = plan()
    assert not answer["ok"] and any("is live" in b for b in answer["blockers"])
    with pytest.raises(HTTPException) as caught:
        apply(answer["fingerprint"])
    assert caught.value.status_code == 409
    assert world.files["transcript"].exists()


def test_unlistable_socket_is_refused(world: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(routes, "_panes", lambda: (False, ()))
    assert any("cannot be proven asleep" in b for b in plan()["blockers"])


def test_fork_parent_is_refused(world: Any) -> None:
    with closing(connect(world.db)) as conn:
        W.add_session(conn, "sess-child", "carnivore_child", "99999999-0000-0000-0000-000000000000", parent=world.row)
    assert any("forked or resumed" in b for b in plan()["blockers"])


@pytest.mark.parametrize("beast, typed, quoted, status", [
    (False, W.TITLE, None, 403),
    (True, "purge  me", None, 422),
    (True, None, None, 422),
    (True, W.TITLE, "0000000000000000", 412),
    (True, W.TITLE, "", 428),
])
def test_gates_refuse_and_delete_nothing(world: Any, beast: bool, typed: Any, quoted: Any, status: int) -> None:
    fingerprint = plan()["fingerprint"] if quoted is None else quoted
    with pytest.raises(HTTPException) as caught:
        apply(fingerprint, typed=typed, beast=beast)
    assert caught.value.status_code == status
    assert all(p.exists() for p in world.files.values())
    assert rows(world, "sessions", "session_uuid = ?", W.UUID) == 1
    assert not (world.state / "purge-receipts").exists()


@pytest.mark.parametrize("arg", sorted(session_purge_tools.CONFIRMATION_ARGS))
def test_agent_cannot_pass_the_confirmation(arg: str) -> None:
    with pytest.raises(ToolError, match="owner types the confirmation"):
        asyncio.run(session_purge_tools.session_purge(None, None, {"target": W.UUID, "apply": True, arg: W.TITLE}))


def test_approve_requires_the_owners_exact_typed_text() -> None:
    store = pending.PendingActions()
    seen: list = []

    async def execute() -> dict:
        seen.append(typed_confirm.typed_answer())
        return {"content": [], "isError": False}

    async def scenario() -> None:
        item = store.create(caller_session_id="c", caller_tmux="agent", target_session_id=W.UUID, target_tmux="",
                            action="session_purge", args_summary="purge", execute=execute, beast_eligible=False,
                            extra={"confirm_text": W.TITLE})
        assert item.as_dict()["confirm_text"] == W.TITLE
        for wrong in (None, "", "Purge me", W.TITLE + " "):
            with pytest.raises(typed_confirm.ConfirmationMismatch):
                await store.approve(item.id, typed=wrong)
            assert store.get(item.id).status == pending.PENDING
        assert seen == []
        await store.approve(item.id, typed=W.TITLE)
        assert seen == [W.TITLE] and store.get(item.id).status == pending.APPROVED
        assert typed_confirm.typed_answer() is None

    asyncio.run(scenario())


def test_purge_always_waits_and_runs_nothing_without_the_owners_text() -> None:
    from src.core.mcp import beast_mode

    assert "session_purge" in beast_mode.ALWAYS_WAITS
    assert not beast_mode.eligible_action("session_purge")
    store = pending.PendingActions()
    ran: list = []

    async def execute() -> dict:
        ran.append(typed_confirm.typed_answer())
        return {"content": [], "isError": False}

    async def scenario() -> None:
        item = store.create(caller_session_id="c", caller_tmux="agent", target_session_id=W.UUID, target_tmux="",
                            action="session_purge", args_summary="purge", execute=execute, beast_eligible=True,
                            extra={"confirm_text": W.TITLE})
        assert store.beast_candidates() == []
        await store.execute_claimed(store.claim_for_beast(item.id))
        assert ran == [None]

    asyncio.run(scenario())


def _seed_corpus(world: Any) -> dict:
    from src.core import message_block_ddl, message_block_search_ddl, message_model_ddl

    with closing(connect(world.db)) as conn:
        for ddl in (*message_model_ddl.DDL_V16, *message_block_ddl.DDL_V18, *message_block_search_ddl.DDL_V31):
            conn.execute(ddl)
        common = {"session_ref_scheme": "uuid", "line_ending": "LF", "has_trailing_newline": 1}
        ours = W.insert(conn, "message_transcripts", source_ref=f"M::claude-projects::-w-proj/{W.CONV}.jsonl",
                        session_ref=W.CONV, **common)
        other = W.insert(conn, "message_transcripts", source_ref="M::claude-projects::-w-proj/other.jsonl",
                         session_ref="other-conv", **common)
        only = W.insert(conn, "message_bodies", identity_key="k-only", body_json="{}")
        both = W.insert(conn, "message_bodies", identity_key="k-both", body_json="{}")
        line = {"line_status": "ok", "fidelity_outcome": "fidelity_verified"}
        W.insert(conn, "message_appearances", transcript_id=ours, line_no=1, body_id=only, **line)
        W.insert(conn, "message_appearances", transcript_id=ours, line_no=2, body_id=both, **line)
        W.insert(conn, "message_appearances", transcript_id=other, line_no=1, body_id=both, **line)
        W.insert(conn, "session_search_docs", conversation_id=W.CONV, point_id="p1")
    return {"ours": ours, "other": other, "only": only, "both": both}


def _seed_cache(world: Any) -> None:
    from src.core.deepsearch.cache import db as cache_db
    from src.core.deepsearch.live import store

    with closing(cache_db.open_cache(world.state)) as conn:
        live_id = store.save(conn, store.LiveFile(W.CONV, "/t/c.jsonl", "conversation", "claude", 0, 0, None, 5, 1,
                                                  None, None, 1, "v", 1, "human", "2026-10-09", "2026-10-09"))
        row = conn.execute("INSERT INTO session_search_rows (doc_id, frame_index, frame_offset, frame_len, "
                           "frame_first_line, line, kind, live_id) VALUES (0, 0, 0, 5, 0, 0, 'user', ?)", (live_id,))
        conn.execute("INSERT INTO session_search_fts (rowid, body) VALUES (?, 'hello')", (row.lastrowid,))


def test_corpus_and_search_index_go_but_a_shared_body_stays(world: Any) -> None:
    ids = _seed_corpus(world)
    _seed_cache(world)
    found = by_what(plan())
    assert found[("cloude.db", "message_transcripts")]["count"] == 1
    assert found[("cloude.db", "message_bodies (only those no other conversation shows)")]["count"] == 1
    assert not [k for k in found if k[0] == "cloude.db" and k[1].startswith("session_search_")], found
    assert found[("deepsearch.db", "session_search_live (with its rows and postings)")]["count"] == 1
    assert apply(plan()["fingerprint"])["done"]["status"] == "done"
    assert rows(world, "message_transcripts", "id = ?", ids["ours"]) == 0
    assert rows(world, "message_transcripts", "id = ?", ids["other"]) == 1
    assert rows(world, "message_bodies", "id = ?", ids["only"]) == 0
    assert rows(world, "message_bodies", "id = ?", ids["both"]) == 1
    assert rows(world, "message_appearances", "transcript_id = ?", ids["other"]) == 1
    assert rows(world, "session_search_docs", "conversation_id = ?", W.CONV) == 1
    from src.core.deepsearch.cache import db as cache_db

    with closing(cache_db.open_cache(world.state)) as conn:
        assert [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("session_search_live", "session_search_rows")] == [0, 0]


def test_a_report_row_that_appears_between_plan_and_apply_does_not_refuse(world: Any) -> None:
    fingerprint = plan()["fingerprint"]
    with closing(connect(world.db)) as conn:
        W.insert(conn, "mcp_events", caller_session_id=W.UUID, caller_kind="pane")
        conn.commit()
    answer = apply(fingerprint)
    assert answer["done"]["status"] == "done"
    assert rows(world, "mcp_events", "caller_session_id = ?", W.UUID) == 1, "a report row is listed and never deleted"


def test_a_deleted_row_that_changes_between_plan_and_apply_still_refuses(world: Any) -> None:
    fingerprint = plan()["fingerprint"]
    with closing(connect(world.db)) as conn:
        W.insert(conn, "conversation_milestones", conversation_id=W.CONV, session_uuid=W.UUID, kind="stop", source="scan",
                 created_at="now")
        conn.commit()
    with pytest.raises(HTTPException) as refused:
        apply(fingerprint)
    assert refused.value.status_code == 412


def test_a_stray_file_of_an_earlier_conversation_does_not_block_but_the_current_ones_does(world: Any, tmp_path: Any) -> None:
    older = "older-conversation-0001"
    with closing(connect(world.db)) as conn:
        W.insert(conn, "conversation_milestones", conversation_id=older, session_uuid=W.UUID, kind="start", source="scan",
                 created_at="now")
        conn.commit()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (world.home / "projects" / "-evil").symlink_to(outside)
    (outside / f"{older}.jsonl").write_text("{}\n")
    answer = plan()
    assert answer["ok"] and not [b for b in answer["blockers"] if older in b or "elsewhere" in b], answer["blockers"]
    (outside / f"{W.CONV}.jsonl").write_text("{}\n")
    blocked = plan()
    assert not blocked["ok"] and any("resolves outside" in b for b in blocked["blockers"])


def test_the_database_phase_ignores_a_report_row_added_after_the_plan_was_built(world: Any) -> None:
    from src.core.inventory import db_trace
    from src.core.session_purge import apply as apply_mod, plan as plan_mod

    with closing(connect(world.db)) as conn:
        built = plan_mod.build_plan(conn, W.UUID, state_dir=world.state, config_path=world.config, panes=(True, []),
                                    homes=[world.home])
        W.insert(conn, "mcp_events", caller_session_id=W.UUID, caller_kind="pane")
        conn.commit()
        outcomes = apply_mod._db_phase(conn, built, [a for a in built.artifacts if a.store == db_trace.STORE])
    assert any(o["what"] == "mcp_events" and o["status"] == "report" for o in outcomes)
    assert rows(world, "sessions", "session_uuid = ?", W.UUID) == 0 and rows(world, "mcp_events", "1 = 1") == 1

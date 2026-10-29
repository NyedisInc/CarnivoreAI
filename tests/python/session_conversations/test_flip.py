
from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import settings
from src.core.db import connect, db_path_for, transaction
from src.core.db_models import SESSION_ORIGIN_ADOPTED
from src.core.session_claude_correlate_bind import bind_correlated_uuid
from src.core.session_conversation_rebind import REBIND_WROTE, rebind_conversation_uuid
from src.core.pipeline import triggers
from src.core.session_identity import record_instance
from tests.s7_helpers import TEST_SOCKET, migrated_connection, session_row
from tests.test_session_conversation_rebind import EPOCH, NAME, RebindManager

from .helpers import A_ID, B_ID, C_ID, WORKING_DIR, command_lines, fork_lines, normal_lines, write_transcript

MTIME = 1_789_000_000


@pytest.fixture()
def world(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    corpus = tmp_path / "projects"
    corpus.mkdir()
    with closing(migrated_connection(state)) as conn:
        with transaction(conn):
            record_instance(conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH, origin=SESSION_ORIGIN_ADOPTED,
                            working_dir=WORKING_DIR)
            bind_correlated_uuid(conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH, claude_uuid=A_ID)
    submitted = []
    real = triggers.schedule_for_conversation

    def spy(conversation_id, session_uuid, reason, **kw):
        future = real(conversation_id, session_uuid, reason, **kw)
        submitted.append(((conversation_id, session_uuid, reason, kw), future))
        return future

    monkeypatch.setattr(triggers, "schedule_for_conversation", spy)
    write_transcript(corpus, A_ID, normal_lines("the old task"), mtime=MTIME)
    yield type("W", (), {"state": state, "corpus": corpus, "manager": RebindManager(state), "submitted": submitted})
    for _call, future in submitted:
        if future is not None:
            future.result(timeout=30)


def _flip(world, new_id):
    return rebind_conversation_uuid(world.manager, session_id="ses_x", tmux_name=NAME, epoch=EPOCH,
                                    registry_uuid=new_id, corpus_root=world.corpus)


def _settle(world):
    for _call, future in world.submitted:
        future.result(timeout=30)


def _index(world, conversation_id):
    with closing(connect(db_path_for(world.state))) as conn:
        row = conn.execute("SELECT * FROM conversation_index WHERE conversation_id = ?", (conversation_id,)).fetchone()
        return dict(row) if row else None


def test_no_second_table_exists(world):
    with closing(connect(db_path_for(world.state))) as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'session_conversations'").fetchone() is None


def test_a_clear_saves_the_old_conversation_and_the_row_points_at_the_new_one(world):
    write_transcript(world.corpus, B_ID, command_lines("/clear", prompt="the new task"), mtime=MTIME + 600)
    assert _flip(world, B_ID).outcome == REBIND_WROTE
    (call, future), = world.submitted
    assert call[0] == A_ID and call[2] == "clear" and call[3]["child_conversation_id"] == B_ID
    assert future.result(timeout=30).state == "done"
    with closing(connect(db_path_for(world.state))) as conn:
        row = session_row(conn, NAME)
        kinds = [r[0] for r in conn.execute("SELECT kind FROM conversation_milestones WHERE conversation_id = ?", (A_ID,))]
    assert row["claude_session_uuid"] == B_ID and call[1] == row["session_uuid"]
    assert kinds == ["clear"] and _index(world, A_ID) is None and not (world.state / "time-machine").exists()


def test_no_overwrite_regression_the_old_conversation_stays_reachable(world):
    from src.core.session_conversations import view

    write_transcript(world.corpus, B_ID, command_lines("/clear"), mtime=MTIME + 600)
    _flip(world, B_ID)
    _settle(world)
    with closing(connect(db_path_for(world.state))) as conn:
        uuid = session_row(conn, NAME)["session_uuid"]
        built = view.build(conn, uuid, corpus_root=world.corpus)
        counts = view.previous_counts(conn)
    assert built["current"]["conversation_id"] == B_ID
    assert [p["conversation_id"] for p in built["previous"]] == [A_ID]
    assert built["previous"][0]["transcript_on_disk"] is True and built["previous"][0]["ended_reason"] == "clear"
    assert counts == {uuid: 1}


def test_reset_and_new_save_under_the_one_clear_event(world):
    write_transcript(world.corpus, B_ID, command_lines("/reset"), mtime=MTIME + 600)
    _flip(world, B_ID)
    assert [c[2] for c, _f in world.submitted] == ["clear"]


def test_a_fork_flip_saves_as_fork_and_an_unreadable_reason_as_switch_never_clear(world):
    write_transcript(world.corpus, B_ID, fork_lines(A_ID), mtime=MTIME + 600)
    write_transcript(world.corpus, C_ID, normal_lines("a plain start"), mtime=MTIME + 1200)
    _flip(world, B_ID)
    _settle(world)
    _flip(world, C_ID)
    assert [c[2] for c, _f in world.submitted] == ["fork", "switch"]


def _edges(world):
    with closing(connect(db_path_for(world.state))) as conn:
        return {tuple(r) for r in conn.execute("SELECT parent_id, child_type, edge_kind, link_basis FROM lineage_edges "
                                               "WHERE child_type = 'conversation'").fetchall()}


def test_two_clears_chain_the_parent(world):
    write_transcript(world.corpus, B_ID, command_lines("/clear"), mtime=MTIME + 600)
    write_transcript(world.corpus, C_ID, command_lines("/reset", prompt="third"), mtime=MTIME + 1200)
    _flip(world, B_ID)
    _settle(world)
    _flip(world, C_ID)
    _settle(world)
    assert [c[0] for c, _f in world.submitted] == [A_ID, B_ID]
    assert world.submitted[1][0][3]["child_conversation_id"] == C_ID
    assert _edges(world) == {(A_ID, "conversation", "clear", "recorded"), (B_ID, "conversation", "clear", "recorded")}
    with closing(connect(db_path_for(world.state))) as conn:
        kinds = [r[0] for r in conn.execute("SELECT kind FROM conversation_milestones WHERE source = 'pipeline' ORDER BY id")]
    assert kinds == ["clear", "clear"]


def test_a_refused_rebind_saves_nothing(world):
    _flip(world, B_ID)
    with closing(connect(db_path_for(world.state))) as conn:
        assert session_row(conn, NAME)["claude_session_uuid"] == A_ID
    assert world.submitted == []


def test_a_refused_pool_never_undoes_the_rebind(world, monkeypatch):
    monkeypatch.setattr(triggers, "schedule_for_conversation", lambda *a, **k: None)
    write_transcript(world.corpus, B_ID, command_lines("/clear"), mtime=MTIME + 600)
    assert _flip(world, B_ID).outcome == REBIND_WROTE
    with closing(connect(db_path_for(world.state))) as conn:
        assert session_row(conn, NAME)["claude_session_uuid"] == B_ID

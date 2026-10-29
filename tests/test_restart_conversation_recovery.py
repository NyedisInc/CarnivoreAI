
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import claude_transcript_correlate
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.session_restart import (
    RESTART_CONVERSATION_MISSING,
    RESTART_RESUMABLE,
    resolve_restart_source,
)
from src.core.session_transcript_presence import (
    CONVERSATION_ABSENT,
    CONVERSATION_PRESENT,
    CONVERSATION_UNCHECKED,
    conversation_presence,
)
from src.core.trail_entry import utc_now

ANCHOR_UUID = "c33e4ce2-17ea-4320-aa28-36204c4d13c5"
HEAD_UUID = "2629dba5-234e-44d2-be54-ddaf69c8db4b"
WORKING_DIR = "/Users/x/Development/CloudeCode"


@pytest.fixture
def conn(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    c = connect(db_path_for(state))
    yield c
    c.close()


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(
        claude_transcript_correlate, "default_projects_dir", lambda: root
    )
    return root


def _write_transcript(corpus_root: Path, uuid: str, slug: str = "-Users-x-proj"):
    project = corpus_root / slug
    project.mkdir(parents=True, exist_ok=True)
    path = project / f"{uuid}.jsonl"
    path.write_text('{"type":"user"}\n', encoding="utf-8")
    return path


def _insert(conn, **overrides):
    row = {
        "session_uuid": "row-uuid",
        "origin": "created",
        "tmux_socket": "cloude",
        "tmux_name": "cloude_CloudeCode",
        "tmux_created_epoch": 1788787880,
        "working_dir": WORKING_DIR,
        "agent_type": "claude-skip-permissions",
        "title": "Agent - Cloude Code",
        "lifecycle": "stopped",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    row.update(overrides)
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with transaction(conn):
        cur = conn.execute(
            f"INSERT INTO sessions ({cols}) VALUES ({marks})", list(row.values())
        )
    return int(cur.lastrowid)


def test_restart_resumes_the_lineage_head_not_the_anchors_first_uuid(
    conn, corpus
):
    _write_transcript(corpus, ANCHOR_UUID)
    _write_transcript(corpus, HEAD_UUID)

    anchor_id = _insert(
        conn, session_uuid="anchor", claude_session_uuid=ANCHOR_UUID
    )
    _insert(
        conn,
        session_uuid="head",
        claude_session_uuid=HEAD_UUID,
        tmux_created_epoch=None,
        parent_session_id=anchor_id,
        fork_kind="unknown",
    )

    source = resolve_restart_source(conn, session_uuid="anchor")

    assert source.outcome == RESTART_RESUMABLE
    assert source.claude_session_uuid == HEAD_UUID, (
        "restart resumed the anchor's first conversation instead of the "
        "one the pane was actually having"
    )
    assert source.parent_id == anchor_id


FORK_UUID = "f3296194-3131-48ed-aeaf-27f931d7a131"


def _insert_gui_fork(conn, parent_id):
    return _insert(
        conn,
        session_uuid="gui-fork",
        claude_session_uuid=FORK_UUID,
        tmux_name="cloude_Agent_-_Cloude_Code_fork",
        tmux_created_epoch=1788902385,
        parent_session_id=parent_id,
        fork_kind="fork",
    )


def test_restart_never_steps_into_a_gui_fork_that_is_its_own_session(
    conn, corpus
):
    from src.core.session_lineage import lineage_head

    _write_transcript(corpus, HEAD_UUID)
    _write_transcript(corpus, FORK_UUID)
    anchor_id = _insert(conn, session_uuid="anchor", claude_session_uuid=HEAD_UUID)
    fork_id = _insert_gui_fork(conn, anchor_id)

    assert int(lineage_head(conn, anchor_id)["id"]) == anchor_id
    source = resolve_restart_source(conn, session_uuid="anchor")
    assert source.outcome == RESTART_RESUMABLE
    assert source.claude_session_uuid == HEAD_UUID, (
        "restarting the parent resumed its GUI fork's conversation"
    )
    assert source.conversation_row_id is None
    assert source.parent_id == anchor_id
    fork_source = resolve_restart_source(conn, session_uuid="gui-fork")
    assert fork_source.claude_session_uuid == FORK_UUID
    assert fork_source.parent_id == fork_id


def test_a_continuation_still_resolves_to_its_head_beside_a_gui_fork(
    conn, corpus
):
    from src.core.session_lineage import lineage_head

    _write_transcript(corpus, ANCHOR_UUID)
    _write_transcript(corpus, HEAD_UUID)
    _write_transcript(corpus, FORK_UUID)
    anchor_id = _insert(conn, session_uuid="anchor", claude_session_uuid=ANCHOR_UUID)
    head_id = _insert(
        conn,
        session_uuid="head",
        claude_session_uuid=HEAD_UUID,
        tmux_created_epoch=None,
        parent_session_id=anchor_id,
        fork_kind="fork",
    )
    fork_id = _insert_gui_fork(conn, anchor_id)
    assert fork_id > head_id

    assert int(lineage_head(conn, anchor_id)["id"]) == head_id
    source = resolve_restart_source(conn, session_uuid="anchor")
    assert source.claude_session_uuid == HEAD_UUID
    assert source.conversation_row_id == head_id


def test_restart_refuses_a_conversation_with_no_transcript_on_disk(
    conn, corpus
):
    _write_transcript(corpus, HEAD_UUID)

    _insert(conn, session_uuid="anchor", claude_session_uuid=ANCHOR_UUID)

    source = resolve_restart_source(conn, session_uuid="anchor")

    assert source.outcome == RESTART_CONVERSATION_MISSING
    assert source.claude_session_uuid == ANCHOR_UUID
    assert ANCHOR_UUID in (source.detail or "")


def test_an_unreadable_corpus_never_refuses_a_restart(conn, tmp_path, monkeypatch):
    missing = tmp_path / "no-such-corpus"
    monkeypatch.setattr(
        claude_transcript_correlate, "default_projects_dir", lambda: missing
    )
    _insert(conn, session_uuid="anchor", claude_session_uuid=ANCHOR_UUID)

    source = resolve_restart_source(conn, session_uuid="anchor")

    assert source.outcome == RESTART_RESUMABLE


def test_presence_probe_reports_three_distinct_outcomes(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    _write_transcript(root, HEAD_UUID)

    found = conversation_presence(HEAD_UUID, corpus_root=root)
    assert found.outcome == CONVERSATION_PRESENT
    assert found.missing is False

    gone = conversation_presence(ANCHOR_UUID, corpus_root=root)
    assert gone.outcome == CONVERSATION_ABSENT
    assert gone.missing is True

    unreadable = conversation_presence(
        ANCHOR_UUID, corpus_root=tmp_path / "nope"
    )
    assert unreadable.outcome == CONVERSATION_UNCHECKED
    assert unreadable.missing is False


def test_presence_probe_finds_a_transcript_the_slug_function_would_miss(
    tmp_path,
):
    root = tmp_path / "projects"
    root.mkdir()
    real_slug = (
        "-Users-x-Library-Mobile-Documents-com-apple-CloudDocs-Sync-"
        "Development-CloudeCode"
    )
    _write_transcript(root, HEAD_UUID, slug=real_slug)

    result = conversation_presence(
        HEAD_UUID,
        working_dir=(
            "/Users/x/Library/Mobile Documents/com~apple~CloudDocs/Sync/"
            "Development/CloudeCode"
        ),
        corpus_root=root,
    )

    assert result.outcome == CONVERSATION_PRESENT

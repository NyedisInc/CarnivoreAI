
from __future__ import annotations

import os
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import (
    SESSION_FORK_KIND_CLEAR,
    SESSION_FORK_KIND_FORK,
    SESSION_FORK_KIND_UNKNOWN,
    SESSION_LIFECYCLE_STOPPED,
    SESSION_ORIGIN_CREATED,
)
from src.core.session_identity import record_instance
from src.core.session_lineage import (
    LINEAGE_BOUND,
    LINEAGE_CONTINUED,
    LINEAGE_FORKED,
    LINEAGE_UNRESOLVED,
    classify_fork_kind,
    lineage_chain,
    record_claude_session,
)
from src.core.session_store import (
    get_instance,
    list_sessions,
    needs_attention,
    owned_instances,
)

SOCKET = "cloude"
NAME = "cloude_proj"
EPOCH = 1_700_000_000


@pytest.fixture()
def conn(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection


@pytest.fixture()
def anchor(conn):
    with transaction(conn):
        result = record_instance(
            conn,
            socket=SOCKET,
            name=NAME,
            epoch=EPOCH,
            origin=SESSION_ORIGIN_CREATED,
            working_dir="/tmp/proj",
        )
    return result.session_id


def _record(conn, claude_uuid, source, **kwargs):
    with transaction(conn):
        return record_claude_session(
            conn,
            socket=kwargs.pop("socket", SOCKET),
            name=kwargs.pop("name", NAME),
            epoch=kwargs.pop("epoch", EPOCH),
            claude_uuid=claude_uuid,
            source=source,
            **kwargs,
        )




def test_v1_0_3_never_wrote_the_lineage_columns(conn, anchor):
    row = get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH)
    assert row["claude_session_uuid"] is None
    assert row["parent_session_id"] is None
    assert row["fork_kind"] is None


def test_startup_binds_the_uuid_to_the_anchor_row(conn, anchor):
    result = _record(conn, "uuid-A", "startup")
    assert result.outcome == LINEAGE_BOUND
    assert result.row_id == anchor

    row = get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH)
    assert row["claude_session_uuid"] == "uuid-A"
    assert row["parent_session_id"] is None
    assert len(list_sessions(conn, include_lineage=True)) == 1




def test_fork_creates_a_second_row_pointing_at_the_first(conn, anchor):
    _record(conn, "uuid-A", "startup")
    result = _record(conn, "uuid-B", "fork")

    assert result.outcome == LINEAGE_FORKED
    assert result.parent_row_id == anchor
    assert result.fork_kind == SESSION_FORK_KIND_FORK

    rows = list_sessions(conn, include_lineage=True)
    assert len(rows) == 2

    child = [r for r in rows if r["id"] == result.row_id][0]
    parent = [r for r in rows if r["id"] == anchor][0]

    assert child["parent_session_id"] == anchor
    assert child["claude_session_uuid"] == "uuid-B"
    assert child["fork_kind"] == SESSION_FORK_KIND_FORK
    assert parent["claude_session_uuid"] == "uuid-A"
    assert parent["parent_session_id"] is None


def test_the_forked_row_carries_what_reopening_needs(conn, anchor):
    _record(conn, "uuid-A", "startup")
    result = _record(conn, "uuid-B", "fork")

    child = [
        r for r in list_sessions(conn, include_lineage=True) if r["id"] == result.row_id
    ][0]
    assert child["claude_session_uuid"] == "uuid-B"
    assert child["working_dir"] == "/tmp/proj"
    assert child["origin"] == SESSION_ORIGIN_CREATED
    assert child["lifecycle"] == SESSION_LIFECYCLE_STOPPED


def test_a_second_fork_parents_onto_the_head_not_the_root(conn, anchor):
    _record(conn, "uuid-A", "startup")
    first = _record(conn, "uuid-B", "fork")
    second = _record(conn, "uuid-C", "fork")

    assert second.parent_row_id == first.row_id
    assert second.parent_row_id != anchor

    chain = lineage_chain(conn, second.row_id)
    assert [r["claude_session_uuid"] for r in chain] == [
        "uuid-A",
        "uuid-B",
        "uuid-C",
    ]




def test_clear_is_a_new_row_and_says_it_was_a_clear(conn, anchor):
    _record(conn, "uuid-A", "startup")
    result = _record(conn, "uuid-B", "clear")
    assert result.outcome == LINEAGE_FORKED
    assert result.fork_kind == SESSION_FORK_KIND_CLEAR
    assert result.parent_row_id == anchor


def test_compact_is_the_same_session_continuing(conn, anchor):
    _record(conn, "uuid-A", "startup")
    result = _record(conn, "uuid-A", "compact")
    assert result.outcome == LINEAGE_CONTINUED
    assert len(list_sessions(conn, include_lineage=True)) == 1


def test_resume_of_the_same_conversation_is_not_a_fork(conn, anchor):
    _record(conn, "uuid-A", "startup")
    result = _record(conn, "uuid-A", "resume")
    assert result.outcome == LINEAGE_CONTINUED
    assert len(list_sessions(conn, include_lineage=True)) == 1


def test_a_duplicate_hook_delivery_writes_nothing(conn, anchor):
    _record(conn, "uuid-A", "startup")
    _record(conn, "uuid-B", "fork")
    before = list_sessions(conn, include_lineage=True)

    again = _record(conn, "uuid-B", "fork")

    assert again.outcome == LINEAGE_CONTINUED
    assert not again.wrote
    assert list_sessions(conn, include_lineage=True) == before


def test_an_unknown_source_forks_honestly_rather_than_guessing(conn, anchor):
    _record(conn, "uuid-A", "startup")
    result = _record(conn, "uuid-B", "teleport_from_the_future")
    assert result.outcome == LINEAGE_FORKED
    assert result.fork_kind == SESSION_FORK_KIND_UNKNOWN


def test_classify_fork_kind_never_invents_a_kind():
    assert classify_fork_kind("fork") == SESSION_FORK_KIND_FORK
    assert classify_fork_kind("clear") == SESSION_FORK_KIND_CLEAR
    assert classify_fork_kind(None) == SESSION_FORK_KIND_UNKNOWN
    assert classify_fork_kind("") == SESSION_FORK_KIND_UNKNOWN
    assert classify_fork_kind("startup") == SESSION_FORK_KIND_UNKNOWN




def test_an_unknown_tmux_instance_is_unresolved_not_a_new_session(conn):
    result = _record(conn, "uuid-A", "startup", name="never-recorded")
    assert result.outcome == LINEAGE_UNRESOLVED
    assert result.detail
    assert list_sessions(conn, include_lineage=True) == []


def test_an_unreadable_epoch_is_unresolved(conn, anchor):
    result = _record(conn, "uuid-A", "startup", epoch=None)
    assert result.outcome == LINEAGE_UNRESOLVED
    assert len(list_sessions(conn, include_lineage=True)) == 1


def test_an_empty_payload_session_id_is_unresolved(conn, anchor):
    result = _record(conn, "", "startup")
    assert result.outcome == LINEAGE_UNRESOLVED




def test_a_lineage_row_cannot_be_mistaken_for_a_tmux_instance(conn, anchor):
    _record(conn, "uuid-A", "startup")
    forked = _record(conn, "uuid-B", "fork")

    assert get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH)["id"] == anchor
    assert owned_instances(conn, socket=SOCKET) == {(NAME, EPOCH)}
    ids = [r["id"] for r in list_sessions(conn)]
    assert anchor in ids
    assert forked.row_id not in ids


def test_lineage_rows_do_not_enter_needs_attention(conn, anchor):
    _record(conn, "uuid-A", "startup")
    _record(conn, "uuid-B", "fork")
    assert all(r["parent_session_id"] is None for r in needs_attention(conn))


def test_rows_that_predate_lineage_are_untouched_and_still_listed(conn, anchor):
    before = get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH)
    assert before["claude_session_uuid"] is None

    with transaction(conn):
        record_instance(
            conn,
            socket=SOCKET,
            name="other",
            epoch=EPOCH + 1,
            origin=SESSION_ORIGIN_CREATED,
        )
    _record(conn, "uuid-A", "startup", name="other", epoch=EPOCH + 1)
    _record(conn, "uuid-B", "fork", name="other", epoch=EPOCH + 1)

    after = get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH)
    assert after == before
    assert anchor in [r["id"] for r in list_sessions(conn)]


def test_claude_title_tracks_claudes_current_name(conn, anchor):
    _record(conn, "uuid-A", "startup", title="first title")
    row = get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH)
    assert row["claude_title"] == "first title"

    _record(conn, "uuid-A", "compact", title="a later, different title")
    row = get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH)
    assert row["claude_title"] == "a later, different title"


def test_claude_title_never_touches_the_user_label(conn, anchor):
    _record(conn, "uuid-A", "startup", title="claude picked this")
    row = get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH)
    assert row["title"] is None, "Claude's name must never become the user label"

    _record(conn, "uuid-A", "compact", title=None)
    row = get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH)
    assert row["claude_title"] == "claude picked this"


def test_a_forked_row_never_takes_the_user_label_from_claude(conn, anchor):
    _record(conn, "uuid-A", "startup")
    _record(conn, "uuid-B", "clear", title="claude picked this")

    rows = [dict(r) for r in conn.execute(
        "SELECT title, claude_title, fork_kind FROM sessions "
        "WHERE fork_kind = 'clear'"
    )]
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] is None, (
        "Claude's session_title must never become the user's label"
    )
    assert row["claude_title"] == "claude picked this"


def test_a_forked_row_inherits_the_users_own_label(conn, anchor):
    conn.execute(
        "UPDATE sessions SET title = ? WHERE id = ?", ("My Chosen Name", anchor)
    )
    _record(conn, "uuid-A", "startup")
    _record(conn, "uuid-B", "clear", title="claude picked this")

    row = dict(conn.execute(
        "SELECT title, claude_title FROM sessions WHERE fork_kind = 'clear'"
    ).fetchone())
    assert row["title"] == "My Chosen Name"
    assert row["claude_title"] == "claude picked this"


def test_a_background_fork_never_becomes_the_lineage_head(conn, anchor):
    from src.core.session_lineage import lineage_head

    _record(conn, "uuid-A", "startup")
    head_before = lineage_head(conn, anchor)

    _record(conn, "uuid-BG", "fork", pane_left_previous=False)

    head_after = lineage_head(conn, anchor)
    assert head_after["id"] == head_before["id"], (
        "a background fork must not move the head - the pane is still "
        "running the parent"
    )
    bg = conn.execute(
        "SELECT fork_kind FROM sessions WHERE claude_session_uuid = ?",
        ("uuid-BG",),
    ).fetchone()
    assert bg["fork_kind"] == "background"


def test_a_branch_DOES_become_the_head(conn, anchor):
    from src.core.session_lineage import lineage_head

    _record(conn, "uuid-A", "startup")
    before = lineage_head(conn, anchor)

    _record(conn, "uuid-BR", "fork", pane_left_previous=True)

    after = lineage_head(conn, anchor)
    assert after["id"] != before["id"]
    assert after["claude_session_uuid"] == "uuid-BR"


def test_a_branch_after_a_background_fork_attaches_to_the_real_origin(conn, anchor):
    _record(conn, "uuid-A", "startup")
    origin = conn.execute(
        "SELECT id FROM sessions WHERE claude_session_uuid = ?", ("uuid-A",)
    ).fetchone()

    _record(conn, "uuid-BG", "fork", pane_left_previous=False)
    _record(conn, "uuid-BR", "fork", pane_left_previous=True)

    branch = conn.execute(
        "SELECT parent_session_id FROM sessions WHERE claude_session_uuid = ?",
        ("uuid-BR",),
    ).fetchone()
    assert branch["parent_session_id"] == origin["id"], (
        "the branch must descend from what the pane was running"
    )


def test_a_cleared_anchor_binds_the_registry_conversation_instead_of_calling_it_a_sibling(conn, anchor):
    _record(conn, "uuid-A", "startup")
    _record(conn, "uuid-B", SESSION_FORK_KIND_CLEAR, pane_left_previous=True)
    with transaction(conn):
        conn.execute("UPDATE sessions SET claude_session_uuid = NULL WHERE id = ?", (anchor,))
    result = _record(conn, "uuid-C", "registry")
    assert result.outcome == LINEAGE_BOUND and result.row_id == anchor
    assert get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH)["claude_session_uuid"] == "uuid-C"

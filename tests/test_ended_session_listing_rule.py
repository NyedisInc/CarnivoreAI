
from __future__ import annotations

from contextlib import closing

import pytest

from src.core import session_store
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import (
    SESSION_ATTRIBUTION_UNKNOWN,
    SESSION_LIFECYCLE_STOPPED,
    SESSION_LIFECYCLE_UNKNOWN,
)
from tests.lifecycle_helpers import add_row

ARCHIVED_STAMP = "2026-08-20T00:00:00.000000Z"


@pytest.fixture()
def conn(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection


def _uuids(rows):
    return {str(row["session_uuid"]) for row in rows}




def test_recent_shows_an_ended_session(conn):
    add_row(
        conn,
        uuid="ended",
        name="cloude_ended",
        epoch=1000,
        lifecycle=SESSION_LIFECYCLE_STOPPED,
    )
    rows = session_store.list_sessions(
        conn, lifecycle=SESSION_LIFECYCLE_STOPPED, include_archived=False
    )
    assert "ended" in _uuids(rows)


def test_recent_hides_a_deleted_session(conn):
    add_row(
        conn,
        uuid="deleted",
        name="cloude_deleted",
        epoch=1001,
        lifecycle=SESSION_LIFECYCLE_STOPPED,
        archived_at=ARCHIVED_STAMP,
    )
    rows = session_store.list_sessions(
        conn, lifecycle=SESSION_LIFECYCLE_STOPPED, include_archived=False
    )
    assert "deleted" not in _uuids(rows)




def test_needs_attention_shows_an_unevaluable_session(conn):
    add_row(
        conn,
        uuid="cannot-tell",
        name="cloude_cannot_tell",
        epoch=1002,
        lifecycle=SESSION_LIFECYCLE_UNKNOWN,
    )
    assert "cannot-tell" in _uuids(session_store.needs_attention(conn))


def test_needs_attention_hides_a_deleted_session(conn):
    add_row(
        conn,
        uuid="deleted-unknown",
        name="cloude_deleted_unknown",
        epoch=1003,
        lifecycle=SESSION_LIFECYCLE_UNKNOWN,
        archived_at=ARCHIVED_STAMP,
    )
    assert "deleted-unknown" not in _uuids(session_store.needs_attention(conn))


def test_needs_attention_hides_a_deleted_row_with_unknown_attribution(conn):
    add_row(
        conn,
        uuid="deleted-attr",
        name="cloude_deleted_attr",
        epoch=1004,
        lifecycle=SESSION_LIFECYCLE_STOPPED,
        archived_at=ARCHIVED_STAMP,
    )
    conn.execute(
        "UPDATE sessions SET project_attribution = ? WHERE session_uuid = ?",
        (SESSION_ATTRIBUTION_UNKNOWN, "deleted-attr"),
    )
    assert "deleted-attr" not in _uuids(session_store.needs_attention(conn))




def test_listable_sessions_carries_ended_and_running_and_drops_deleted(conn):
    add_row(conn, uuid="live", name="cloude_live", epoch=2000)
    add_row(
        conn,
        uuid="over",
        name="cloude_over",
        epoch=2001,
        lifecycle=SESSION_LIFECYCLE_STOPPED,
    )
    add_row(
        conn,
        uuid="gone",
        name="cloude_gone",
        epoch=2002,
        lifecycle=SESSION_LIFECYCLE_STOPPED,
        archived_at=ARCHIVED_STAMP,
    )
    got = _uuids(session_store.listable_sessions(conn))
    assert got == {"live", "over"}


def test_listable_sessions_is_empty_on_a_pre_v2_database(tmp_path):
    with closing(connect(db_path_for(tmp_path), create=True)) as fresh:
        assert session_store.listable_sessions(fresh) == []




def test_records_still_returns_archived_rows(conn):
    add_row(
        conn,
        uuid="archived",
        name="cloude_archived",
        epoch=3000,
        lifecycle=SESSION_LIFECYCLE_STOPPED,
        archived_at=ARCHIVED_STAMP,
    )
    assert "archived" in _uuids(session_store.list_sessions(conn))




def test_archive_hides_the_row_from_every_listing_surface(conn):
    add_row(
        conn,
        uuid="doomed",
        name="cloude_doomed",
        epoch=4000,
        lifecycle=SESSION_LIFECYCLE_STOPPED,
    )
    assert session_store.archive_session(conn, "doomed") is True

    assert "doomed" not in _uuids(session_store.listable_sessions(conn))
    assert "doomed" not in _uuids(
        session_store.list_sessions(
            conn, lifecycle=SESSION_LIFECYCLE_STOPPED, include_archived=False
        )
    )
    assert "doomed" not in _uuids(session_store.needs_attention(conn))


def test_archive_retains_the_row(conn):
    add_row(
        conn,
        uuid="kept",
        name="cloude_kept",
        epoch=4001,
        lifecycle=SESSION_LIFECYCLE_STOPPED,
    )
    session_store.archive_session(conn, "kept")

    row = conn.execute(
        "SELECT archived_at, tmux_name, lifecycle FROM sessions "
        "WHERE session_uuid = ?",
        ("kept",),
    ).fetchone()
    assert row is not None, "the row must still exist - this is a soft delete"
    assert row["archived_at"], "archived_at must carry a timestamp"
    assert row["tmux_name"] == "cloude_kept"
    assert row["lifecycle"] == SESSION_LIFECYCLE_STOPPED


def test_archive_is_idempotent_and_keeps_the_first_stamp(conn):
    add_row(
        conn,
        uuid="twice",
        name="cloude_twice",
        epoch=4002,
        lifecycle=SESSION_LIFECYCLE_STOPPED,
        archived_at=ARCHIVED_STAMP,
    )
    assert session_store.archive_session(conn, "twice") is False
    row = conn.execute(
        "SELECT archived_at FROM sessions WHERE session_uuid = ?", ("twice",)
    ).fetchone()
    assert row["archived_at"] == ARCHIVED_STAMP


def test_archive_of_an_unknown_uuid_is_a_named_miss_not_a_silent_success(conn):
    with pytest.raises(session_store.SessionNotFoundError):
        session_store.archive_session(conn, "no-such-session")


def test_archive_touches_exactly_one_row(conn):
    add_row(
        conn,
        uuid="old",
        name="cloude_reused",
        epoch=5000,
        lifecycle=SESSION_LIFECYCLE_STOPPED,
    )
    add_row(conn, uuid="new", name="cloude_reused", epoch=5001)
    session_store.archive_session(conn, "old")

    assert "old" not in _uuids(session_store.listable_sessions(conn))
    assert "new" in _uuids(session_store.listable_sessions(conn))

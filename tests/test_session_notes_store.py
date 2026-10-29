
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.core import session_notes_store as N
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated


@pytest.fixture()
def conn(tmp_path: Path):
    ensure_db_migrated(tmp_path)
    c = connect(db_path_for(tmp_path))
    yield c
    c.close()


def stored(conn: sqlite3.Connection, name: str) -> str:
    session_uuid = f"uuid-{name}"
    with conn:
        conn.execute(
            "INSERT INTO sessions "
            "(session_uuid, tmux_socket, tmux_name, tmux_created_epoch, "
            " origin, lifecycle, created_at, updated_at) "
            "VALUES (?, 'cloude', ?, 1, 'created', 'running', "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (session_uuid, name),
        )
    return session_uuid




def test_the_migration_chain_reaches_the_table(conn) -> None:
    assert N.table_present(conn) is True


def test_a_database_without_the_table_is_cannot_determine(conn) -> None:
    with conn:
        conn.execute("DROP TABLE session_notes")
    with pytest.raises(N.SessionNotesUnavailable):
        N.read_note(conn, "uuid-nothing")
    with pytest.raises(N.SessionNotesUnavailable):
        N.write_note(conn, "uuid-nothing", "x", 0)




def test_absent_reads_as_the_empty_note_at_revision_zero(conn) -> None:
    uuid = stored(conn, "cloude_a")
    result = N.read_note(conn, uuid)
    assert (result.body, result.revision, result.updated_at) == ("", 0, None)


def test_reading_an_absent_note_writes_nothing(conn) -> None:
    uuid = stored(conn, "cloude_a")
    N.read_note(conn, uuid)
    rows = conn.execute("SELECT COUNT(*) FROM session_notes").fetchone()[0]
    assert rows == 0




def test_the_first_write_from_revision_zero_commits_at_one(conn) -> None:
    uuid = stored(conn, "cloude_a")
    result = N.write_note(conn, uuid, "# todo\n\n- check the pipe reader\n", 0)
    assert result.status == N.COMMITTED
    assert result.revision == 1
    assert result.body == "# todo\n\n- check the pipe reader\n"
    assert result.updated_at is not None
    assert N.read_note(conn, uuid).body == "# todo\n\n- check the pipe reader\n"


def test_the_body_is_stored_verbatim_and_never_rendered(conn) -> None:
    uuid = stored(conn, "cloude_a")
    raw = "<img src=x onerror=alert(1)>\n\n  two spaces\ttab\n"
    N.write_note(conn, uuid, raw, 0)
    assert N.read_note(conn, uuid).body == raw


def test_a_stale_write_is_refused_and_carries_the_current_note(conn) -> None:
    uuid = stored(conn, "cloude_a")
    N.write_note(conn, uuid, "mine", 0)

    refused = N.write_note(conn, uuid, "clobber", 0)

    assert refused.status == N.STALE_REVISION
    assert refused.revision == 1
    assert refused.body == "mine"
    assert refused.detail and "1" in refused.detail
    assert N.read_note(conn, uuid).body == "mine"


def test_without_the_check_the_same_write_would_have_landed(conn) -> None:
    uuid = stored(conn, "cloude_a")
    N.write_note(conn, uuid, "mine", 0)
    landed = N.write_note(conn, uuid, "clobber", 1)
    assert landed.status == N.COMMITTED
    assert landed.revision == 2
    assert N.read_note(conn, uuid).body == "clobber"


def test_an_identical_body_moves_no_revision(conn) -> None:
    uuid = stored(conn, "cloude_a")
    N.write_note(conn, uuid, "same", 0)
    again = N.write_note(conn, uuid, "same", 1)
    assert again.status == N.UNCHANGED
    assert again.revision == 1


def test_an_empty_body_is_a_real_note_and_commits(conn) -> None:
    uuid = stored(conn, "cloude_a")
    N.write_note(conn, uuid, "something", 0)
    cleared = N.write_note(conn, uuid, "", 1)
    assert cleared.status == N.COMMITTED
    assert cleared.revision == 2
    assert N.read_note(conn, uuid).body == ""


def test_a_note_over_the_cap_is_refused_with_a_sentence(conn) -> None:
    uuid = stored(conn, "cloude_a")
    too_big = "x" * (N.NOTE_MAX_BYTES + 1)
    refused = N.write_note(conn, uuid, too_big, 0)
    assert refused.status == N.REJECTED_INVALID
    assert refused.revision == 0
    assert refused.body == ""
    assert refused.detail and "256" in refused.detail
    assert conn.execute("SELECT COUNT(*) FROM session_notes").fetchone()[0] == 0


def test_the_cap_is_bytes_not_characters(conn) -> None:
    uuid = stored(conn, "cloude_a")
    body = "€" * (N.NOTE_MAX_BYTES // 3 + 1)
    assert len(body) < N.NOTE_MAX_BYTES
    assert N.write_note(conn, uuid, body, 0).status == N.REJECTED_INVALID


def test_a_note_at_exactly_the_cap_is_accepted(conn) -> None:
    uuid = stored(conn, "cloude_a")
    assert N.write_note(conn, uuid, "x" * N.NOTE_MAX_BYTES, 0).status == N.COMMITTED




def test_two_sessions_hold_two_independent_notes(conn) -> None:
    first = stored(conn, "cloude_a")
    second = stored(conn, "cloude_b")
    N.write_note(conn, first, "first", 0)
    N.write_note(conn, second, "second", 0)
    assert N.read_note(conn, first).body == "first"
    assert N.read_note(conn, second).body == "second"


def test_a_note_for_no_session_row_is_refused_by_the_foreign_key(conn) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            N.write_note(conn, "uuid-nobody", "orphan", 0)


def test_the_note_follows_the_row_through_a_rename(conn) -> None:
    uuid = stored(conn, "cloude_a")
    N.write_note(conn, uuid, "kept", 0)
    with conn:
        conn.execute(
            "UPDATE sessions SET tmux_name = 'cloude_renamed' WHERE session_uuid = ?",
            (uuid,),
        )
    assert N.read_note(conn, uuid).body == "kept"




def test_the_payload_is_one_shape_for_a_read_a_write_and_a_conflict(conn) -> None:
    uuid = stored(conn, "cloude_a")
    read = N.read_note(conn, uuid).as_payload()
    written = N.write_note(conn, uuid, "a", 0).as_payload()
    conflict = N.write_note(conn, uuid, "b", 0).as_payload()
    for field in ("status", "revision", "body", "updated_at"):
        assert field in read
        assert field in written
        assert field in conflict
    assert "detail" not in written
    assert conflict["detail"]

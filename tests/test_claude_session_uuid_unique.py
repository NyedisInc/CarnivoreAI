
from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import closing
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
from src.core.db import connect, db_path_for, get_meta, set_meta, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import (
    CURRENT_SCHEMA_VERSION,
    META_SESSIONS_CLAUDE_UUID_DUPLICATES,
    SESSION_ORIGIN_CREATED,
)
from src.core.db_steps import run_chain
from src.core.session_fork import mark_as_fork
from src.core.session_identity import record_instance
from src.core.session_lineage import record_claude_session
from src.core.session_store import list_sessions

SOCKET = "cloude"


def _all_claude_uuids(conn: sqlite3.Connection) -> list:
    return [
        row["claude_session_uuid"]
        for row in conn.execute(
            "SELECT claude_session_uuid FROM sessions "
            "WHERE claude_session_uuid IS NOT NULL"
        ).fetchall()
    ]


def _assert_still_1_to_1(conn: sqlite3.Connection) -> None:
    uuids = _all_claude_uuids(conn)
    dupes = sorted({u for u in uuids if uuids.count(u) > 1})
    assert not dupes, f"claude_session_uuid claimed by >1 row: {dupes}"




@pytest.fixture()
def conn(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection


def _make_anchor(conn, name, epoch):
    with transaction(conn):
        result = record_instance(
            conn,
            socket=SOCKET,
            name=name,
            epoch=epoch,
            origin=SESSION_ORIGIN_CREATED,
            working_dir="/tmp/proj",
        )
    return result.session_id


def _record(conn, name, epoch, claude_uuid, source, **kwargs):
    with transaction(conn):
        return record_claude_session(
            conn,
            socket=SOCKET,
            name=name,
            epoch=epoch,
            claude_uuid=claude_uuid,
            source=source,
            **kwargs,
        )


def test_startup_fork_clear_compact_never_duplicate_a_uuid(conn):
    anchor = _make_anchor(conn, "cloude_a", 1_700_000_001)

    r1 = _record(conn, "cloude_a", 1_700_000_001, "uuid-A", "startup")
    assert r1.row_id == anchor
    _assert_still_1_to_1(conn)

    r2 = _record(conn, "cloude_a", 1_700_000_001, "uuid-B", "fork")
    assert r2.parent_row_id == anchor
    _assert_still_1_to_1(conn)

    r3 = _record(conn, "cloude_a", 1_700_000_001, "uuid-C", "clear")
    assert r3.parent_row_id == r2.row_id
    _assert_still_1_to_1(conn)

    r4 = _record(conn, "cloude_a", 1_700_000_001, "uuid-C", "compact")
    assert r4.outcome == "continued"
    assert r4.row_id == r3.row_id
    _assert_still_1_to_1(conn)

    r5 = _record(conn, "cloude_a", 1_700_000_001, "uuid-D", "teleport")
    assert r5.parent_row_id == r3.row_id
    _assert_still_1_to_1(conn)

    r6 = _record(conn, "cloude_a", 1_700_000_001, "uuid-D", "teleport")
    assert r6.outcome == "continued"
    assert not r6.wrote
    _assert_still_1_to_1(conn)

    uuids = sorted(_all_claude_uuids(conn))
    assert uuids == ["uuid-A", "uuid-B", "uuid-C", "uuid-D"]


def test_the_same_uuid_replayed_at_an_unrelated_tmux_instance_still_1_to_1(conn):
    anchor_a = _make_anchor(conn, "cloude_a", 1_700_000_010)
    anchor_b = _make_anchor(conn, "cloude_b", 1_700_000_020)

    bound = _record(conn, "cloude_a", 1_700_000_010, "uuid-shared", "startup")
    assert bound.row_id == anchor_a

    replay = _record(conn, "cloude_b", 1_700_000_020, "uuid-shared", "startup")
    assert replay.outcome == "continued"
    assert replay.row_id == anchor_a
    assert not replay.wrote

    _assert_still_1_to_1(conn)
    b_row = [
        r for r in list_sessions(conn, include_lineage=True) if r["id"] == anchor_b
    ][0]
    assert b_row["claude_session_uuid"] is None


def test_gui_fork_path_never_writes_claude_session_uuid(conn):
    parent = _make_anchor(conn, "cloude_parent", 1_700_000_030)
    _record(conn, "cloude_parent", 1_700_000_030, "uuid-parent", "startup")

    child = _make_anchor(conn, "cloude_child", 1_700_000_031)
    row = [r for r in list_sessions(conn) if r["id"] == child][0]
    with transaction(conn):
        wrote = mark_as_fork(
            conn, child_session_uuid=row["session_uuid"], parent_id=parent
        )
    assert wrote is True

    row_after = [r for r in list_sessions(conn) if r["id"] == child][0]
    assert row_after["parent_session_id"] == parent
    assert row_after["claude_session_uuid"] is None

    bound = _record(conn, "cloude_child", 1_700_000_031, "uuid-child", "startup")
    assert bound.outcome == "bound"
    assert bound.row_id == child
    _assert_still_1_to_1(conn)




def _index_names(conn: sqlite3.Connection) -> set:
    return {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='sessions'"
        ).fetchall()
    }


def _insert_raw_session(conn, *, uuid, name, epoch, claude_uuid=None):
    conn.execute(
        "INSERT INTO sessions "
        "(session_uuid, origin, tmux_socket, tmux_name, tmux_created_epoch, "
        " claude_session_uuid, lifecycle, created_at, updated_at) "
        "VALUES (?, 'created', ?, ?, ?, ?, 'running', "
        " '2026-08-29T00:00:00.000000Z', '2026-08-29T00:00:00.000000Z')",
        (uuid, SOCKET, name, epoch, claude_uuid),
    )


def test_fresh_database_migrates_cleanly_to_v12(tmp_path):
    state = ensure_db_migrated(tmp_path, 4, "0.8.2")
    assert state.status == "ok"
    assert state.schema_version == CURRENT_SCHEMA_VERSION

    with closing(connect(db_path_for(tmp_path))) as conn:
        names = _index_names(conn)
        assert "ux_sessions_claude_uuid" in names
        assert "ix_sessions_claude_uuid" not in names

        recorded = get_meta(conn, META_SESSIONS_CLAUDE_UUID_DUPLICATES)
        assert recorded == "[]"


def test_constraint_rejects_a_second_row_for_a_known_uuid(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as conn:
        _insert_raw_session(
            conn, uuid="row-1", name="a", epoch=1, claude_uuid="dup-uuid"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            _insert_raw_session(
                conn, uuid="row-2", name="b", epoch=2, claude_uuid="dup-uuid"
            )
        conn.rollback()


def test_constraint_does_not_apply_to_null_rows(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as conn:
        for i in range(5):
            _insert_raw_session(conn, uuid=f"null-row-{i}", name=f"n{i}", epoch=i)
        conn.commit()
        rows = conn.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE claude_session_uuid IS NULL"
        ).fetchone()
        assert rows["c"] == 5


def test_migration_on_a_database_with_a_planted_duplicate_does_not_crash(tmp_path):
    db_path = db_path_for(tmp_path)
    with closing(connect(db_path)) as conn:
        run_chain(conn, 0, 11)
        conn.commit()
        _insert_raw_session(
            conn, uuid="dup-row-1", name="a", epoch=1, claude_uuid="the-dup-uuid"
        )
        _insert_raw_session(
            conn, uuid="dup-row-2", name="b", epoch=2, claude_uuid="the-dup-uuid"
        )
        conn.commit()

        with transaction(conn):
            run_chain(conn, 11, CURRENT_SCHEMA_VERSION)

        count = conn.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE claude_session_uuid = ?",
            ("the-dup-uuid",),
        ).fetchone()["c"]
        assert count == 2

        rows = sorted(
            r["session_uuid"]
            for r in conn.execute(
                "SELECT session_uuid FROM sessions "
                "WHERE claude_session_uuid = ?",
                ("the-dup-uuid",),
            ).fetchall()
        )
        assert rows == ["dup-row-1", "dup-row-2"]

        names = _index_names(conn)
        assert "ux_sessions_claude_uuid" not in names
        assert "ix_sessions_claude_uuid" in names

        recorded = get_meta(conn, META_SESSIONS_CLAUDE_UUID_DUPLICATES)
        assert recorded is not None
        parsed = json.loads(recorded)
        assert len(parsed) == 1
        assert parsed[0]["claude_session_uuid"] == "the-dup-uuid"
        assert parsed[0]["count"] == 2
        assert sorted(parsed[0]["row_ids"]) == sorted(
            int(
                conn.execute(
                    "SELECT id FROM sessions WHERE session_uuid = ?", (u,)
                ).fetchone()["id"]
            )
            for u in ("dup-row-1", "dup-row-2")
        )

        assert get_meta(conn, "schema_version") == str(CURRENT_SCHEMA_VERSION)


def test_migration_via_ensure_db_migrated_with_a_duplicate_does_not_degrade_boot(
    tmp_path,
):
    db_path = db_path_for(tmp_path)
    with closing(connect(db_path)) as conn:
        run_chain(conn, 0, 11)
        conn.commit()
        _insert_raw_session(
            conn, uuid="boot-dup-1", name="a", epoch=1, claude_uuid="boot-dup-uuid"
        )
        _insert_raw_session(
            conn, uuid="boot-dup-2", name="b", epoch=2, claude_uuid="boot-dup-uuid"
        )
        conn.commit()
        with transaction(conn):
            set_meta(conn, "schema_version", "11")

    state = ensure_db_migrated(tmp_path, 4, "0.8.2")
    assert state.status == "ok"
    assert state.schema_version == CURRENT_SCHEMA_VERSION

    with closing(connect(db_path)) as conn:
        names = _index_names(conn)
        assert "ux_sessions_claude_uuid" not in names
        assert "ix_sessions_claude_uuid" in names
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE claude_session_uuid = ?",
            ("boot-dup-uuid",),
        ).fetchone()["c"]
        assert count == 2


def test_migration_is_idempotent_on_retry(tmp_path):
    db_path = db_path_for(tmp_path)
    with closing(connect(db_path)) as conn:
        run_chain(conn, 0, 11)
        conn.commit()
        with transaction(conn):
            run_chain(conn, 11, CURRENT_SCHEMA_VERSION)
        names_after_first = _index_names(conn)

        from src.core.db_steps import _step_v11_to_v12

        with transaction(conn):
            _step_v11_to_v12(conn)
        names_after_second = _index_names(conn)

        assert names_after_first == names_after_second
        assert "ux_sessions_claude_uuid" in names_after_second


from __future__ import annotations

import sqlite3
from contextlib import closing

from tests.layouts_helpers import add_sessions, grid, migrated, row

# ruff: noqa: E402
from src.core import db_models
from src.core.layouts import store as store
from src.core.archive_db_partition import SIDE_APP, side_for_table
from src.core.db import connect, get_schema_version, table_exists
from src.core.db_schema_audit import UNGATED_VERSION_DDL
from src.core.db_steps import STEPS
from src.core.layouts.ddl import DDL_V34, REVERSAL_SQL_V34, SESSION_DELETE_TRIGGER


def _open(db_path):
    return closing(connect(db_path, create=False))


def test_a_fresh_install_reaches_v34_with_both_tables(tmp_path):
    db_path = migrated(tmp_path / "s")
    with _open(db_path) as conn:
        assert get_schema_version(conn) == db_models.CURRENT_SCHEMA_VERSION >= 34
        assert table_exists(conn, "layouts") and table_exists(conn, "layout_members")


def test_a_v33_database_steps_up_idempotently_and_keeps_its_sessions(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_uuid TEXT)")
    conn.execute("INSERT INTO sessions VALUES (1, 'a')")
    STEPS[33](conn)
    STEPS[33](conn)
    assert table_exists(conn, "layouts") and table_exists(conn, "layout_members")
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_the_step_is_audited_partitioned_and_its_reversal_declared():
    assert UNGATED_VERSION_DDL[34] == DDL_V34
    assert side_for_table("layouts") == SIDE_APP
    assert side_for_table("layout_members") == SIDE_APP
    assert db_models.REVERSAL_SQL_V34 == REVERSAL_SQL_V34
    assert db_models.REVERSAL_DESTROYS[34] == (
        "layouts (whole table)", "layout_members (whole table)")


def test_the_reversal_steps_down_and_leaves_sessions_deletable(tmp_path):
    db_path = migrated(tmp_path / "s")
    (r1, _), (r2, _) = add_sessions(db_path, 2)
    with _open(db_path) as conn:
        store.create_layout(conn, "pair", grid(row(r1), row(r2)))
        for statement in REVERSAL_SQL_V34:
            conn.execute(statement)
        assert not table_exists(conn, "layouts") and not table_exists(conn, "layout_members")
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = ?",
                            (SESSION_DELETE_TRIGGER,)).fetchone()[0] == 0
        conn.execute("DELETE FROM sessions WHERE id = ?", (r1,))
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_deleting_a_session_row_drops_it_and_deletes_a_layout_left_with_one(tmp_path):
    db_path = migrated(tmp_path / "s")
    (a, _), (b, _), (c, _) = add_sessions(db_path, 3)
    with _open(db_path) as conn:
        pair = store.create_layout(conn, "pair", grid(row(a), row(b))).layout
        trio = store.create_layout(conn, "trio", grid(row(a), row(b), row(c))).layout
        conn.execute("DELETE FROM sessions WHERE id = ?", (b,))
        names = [l.name for l in store.list_layouts(conn)]
        assert names == ["trio"]
        left = store.get_layout(conn, trio.layout_uuid)
        assert [m.session_row_id for m in left.members] == [a, c]
        assert left.revision == trio.revision + 1
        assert conn.execute("SELECT COUNT(*) FROM layout_members WHERE session_row_id = ?",
                            (b,)).fetchone()[0] == 0
        assert pair.layout_uuid not in [l.layout_uuid for l in store.list_layouts(conn)]


def test_the_trigger_delete_rolls_back_with_its_transaction(tmp_path):
    db_path = migrated(tmp_path / "s")
    (a, _), (b, _) = add_sessions(db_path, 2)
    with _open(db_path) as conn:
        store.create_layout(conn, "pair", grid(row(a), row(b)))
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM sessions WHERE id = ?", (a,))
        assert store.list_layouts(conn) == []
        conn.execute("ROLLBACK")
        assert [l.name for l in store.list_layouts(conn)] == ["pair"]

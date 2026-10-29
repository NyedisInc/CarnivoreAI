
import sqlite3

from src.core import db_models
from src.core.conversation_index import constants as K
from src.core.conversation_index.ddl import DDL_V46, REVERSAL_SQL_V46
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated


def index_conn(state):
    conn = connect(db_path_for(state), create=False)
    conn.row_factory = sqlite3.Row
    return conn


def insert_row(conn, conversation_id, **fields):
    cols = {"conversation_id": conversation_id, "captured_at": "t", "updated_at": "t", **fields}
    conn.execute(f"INSERT INTO conversation_index ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", tuple(cols.values()))
    return conn.execute("SELECT id FROM conversation_index WHERE conversation_id = ?", (conversation_id,)).fetchone()[0]


def fts_hits(conn, text):
    return [r[0] for r in conn.execute(
        "SELECT rowid FROM conversation_index_fts WHERE conversation_index_fts MATCH ?", (text,))]


def test_version_and_migration_from_v45(tmp_path):
    assert db_models.CURRENT_SCHEMA_VERSION >= 49
    state = tmp_path / "s"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    conn = connect(db_path_for(state), create=False)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert {"conversation_index", "conversation_index_fts", "conversation_index_ai",
                "conversation_index_ad", "conversation_index_au"} <= names
        assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(db_models.CURRENT_SCHEMA_VERSION)
        for stmt in REVERSAL_SQL_V46:
            conn.execute(stmt)
        conn.execute("UPDATE meta SET value='45' WHERE key='schema_version'")
    finally:
        conn.close()
    assert ensure_db_migrated(state).status == "ok"
    conn = connect(db_path_for(state), create=False)
    try:
        assert conn.execute("SELECT COUNT(*) FROM conversation_index").fetchone()[0] == 0
        assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(db_models.CURRENT_SCHEMA_VERSION)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(conversation_index)")}
        assert not cols & {"parent_conversation_id", "link_basis"}
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert {"lineage_edges", "lineage_nodes", "lineage_sources", "conversation_milestones"} <= names
    finally:
        conn.close()


def test_ddl_is_idempotent():
    conn = sqlite3.connect(":memory:")
    for _ in range(2):
        for stmt in DDL_V46:
            conn.execute(stmt)


def test_fts_follows_insert_update_delete(tmp_path):
    state = tmp_path / "s"
    state.mkdir()
    ensure_db_migrated(state)
    conn = index_conn(state)
    try:
        row = insert_row(conn, "conv-aaaa-0001", project_name="Alpha", session_name="Gizmo",
                         first_prompt="build the gizmo", summary="wired the flux capacitor")
        assert fts_hits(conn, "flux*") == [row]
        assert fts_hits(conn, "gizmo") == [row]
        conn.execute("UPDATE conversation_index SET summary = 'rewrote the parser' WHERE id = ?", (row,))
        assert fts_hits(conn, "flux*") == [] and fts_hits(conn, "parser") == [row]
        conn.execute("DELETE FROM conversation_index WHERE id = ?", (row,))
        assert fts_hits(conn, "parser") == [] and fts_hits(conn, "gizmo") == []
        conn.execute("INSERT INTO conversation_index_fts(conversation_index_fts) VALUES ('integrity-check')")
    finally:
        conn.close()


def test_bookkeeping_update_leaves_the_index_alone(tmp_path):
    state = tmp_path / "s"
    state.mkdir()
    ensure_db_migrated(state)
    conn = index_conn(state)
    try:
        row = insert_row(conn, "conv-aaaa-0002", first_prompt="hello world")
        before = conn.total_changes
        conn.execute("UPDATE conversation_index SET summary_attempts = 3, summary_state = 'queued' WHERE id = ?", (row,))
        assert conn.total_changes - before == 1
        assert fts_hits(conn, "hello") == [row]
    finally:
        conn.close()


def test_check_constraint_rejects_unknown_state(tmp_path):
    state = tmp_path / "s"
    state.mkdir()
    ensure_db_migrated(state)
    conn = index_conn(state)
    try:
        row = insert_row(conn, "conv-aaaa-0003")
        try:
            conn.execute("UPDATE conversation_index SET summary_state = 'bogus' WHERE id = ?", (row,))
        except sqlite3.IntegrityError:
            return
        raise AssertionError("bogus state was accepted")
    finally:
        conn.close()


def test_partition_places_every_object_app_side(tmp_path):
    from src.core.archive_db_partition import SIDE_APP, side_for_table

    for name in (K.TABLE, K.FTS_TABLE, *K.FTS_SHADOW_TABLES):
        assert side_for_table(name) == SIDE_APP, name

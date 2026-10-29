
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core import db_models
from src.core.archive_db_partition import SIDE_APP, side_for_table
from src.core.db import connect, db_path_for, get_schema_version, set_meta
from src.core.db_migration import ensure_db_migrated
from src.core.db_schema_audit import (
    AUDIT_MISSING,
    AUDIT_OK,
    SUPERSEDED_OBJECTS,
    UNGATED_VERSION_COLUMNS,
    UNGATED_VERSION_DDL,
    audit_schema,
    repair_missing,
)
from src.core.db_steps import STEPS
from src.core.hosts.ddl import (
    DDL_V40,
    HOST_INSTANCE_INDEX,
    REVERSAL_SQL_V40,
    TRIPLE_INSTANCE_INDEX,
    V40_COLUMNS,
)

STAMP = "2026-09-20T10:00:00.000000Z"


def _open(path: Path):
    return closing(connect(path, create=False))


def _index_sql(conn, name: str):
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def _rewind_to_v39(state_dir: Path) -> None:
    with _open(db_path_for(state_dir)) as conn:
        for statement in REVERSAL_SQL_V40:
            conn.execute(statement)
        conn.execute("ALTER TABLE sessions DROP COLUMN host_key")
        conn.execute("ALTER TABLE projects DROP COLUMN host_key")
        set_meta(conn, db_models.META_SCHEMA_VERSION, "39")


def _seed_real_shape(path: Path) -> None:
    with _open(path) as conn:
        for pid, root, archived in ((1, "/work/api", None), (2, "/work/old", STAMP)):
            conn.execute(
                "INSERT INTO projects (id, root, raw_path, display_name, source, archived_at, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, 'user', ?, ?, ?)",
                (pid, root, root, root.rsplit("/", 1)[1], archived, STAMP, STAMP))
        rows = [
            ("run", "carnivore", "carnivore_api", 1790000200, "created", "running",
             {"project_id": 1, "claude_session_uuid": "c-run", "title": "api", "tmux_session_id": "$3",
              "activity_state": "working", "activity_state_at": STAMP, "working_dir": "/work/api"}),
            ("old", "carnivore", "carnivore_api", 1790000100, "created", "stopped",
             {"project_id": 1, "claude_session_uuid": "c-old", "title": "api"}),
            ("imp", "carnivore", "carnivore_imp", None, "created", "stopped", {"title": "imported"}),
            ("adp", "cloude", "work", 1780000000, "adopted", "running", {"adopted_at": STAMP}),
            ("arc", "carnivore", "carnivore_gone", 1780000500, "created", "stopped",
             {"archived_at": STAMP}),
            ("bot", "carnivore", "carnivore_bot", 1790000300, "created", "running",
             {"kind": "automated", "notifications_muted": 1}),
        ]
        for uuid, socket, name, epoch, origin, lifecycle, extra in rows:
            columns = ["session_uuid", "tmux_socket", "tmux_name", "tmux_created_epoch", "origin",
                       "lifecycle", "created_at", "updated_at", *extra]
            values = [uuid, socket, name, epoch, origin, lifecycle, STAMP, STAMP, *extra.values()]
            conn.execute(f"INSERT INTO sessions ({', '.join(columns)}) VALUES "
                         f"({', '.join('?' for _ in columns)})", values)
        parent = conn.execute("SELECT id FROM sessions WHERE session_uuid = 'run'").fetchone()[0]
        conn.execute(
            "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, origin, "
            "lifecycle, claude_session_uuid, parent_session_id, fork_kind, created_at, updated_at) "
            "VALUES ('frk', 'carnivore', 'carnivore_api', NULL, 'created', 'stopped', 'c-frk', ?, "
            "'background', ?, ?)", (parent, STAMP, STAMP))


def _dump(conn, table: str) -> List[Dict]:
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")]


@pytest.fixture()
def v39_state(tmp_path) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    assert ensure_db_migrated(state_dir).status == "ok"
    _rewind_to_v39(state_dir)
    _seed_real_shape(db_path_for(state_dir))
    return state_dir


def test_the_rewind_really_is_v39(v39_state):
    with _open(db_path_for(v39_state)) as conn:
        assert get_schema_version(conn) == 39
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'hosts'").fetchone() is None
        assert "host_key" not in {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
        assert _index_sql(conn, TRIPLE_INSTANCE_INDEX) is not None
        assert _index_sql(conn, HOST_INSTANCE_INDEX) is None
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 7


def test_a_real_shaped_v39_datastore_upgrades_to_one_local_host_and_local_rows(v39_state):
    path = db_path_for(v39_state)
    with _open(path) as conn:
        sessions_before, projects_before = _dump(conn, "sessions"), _dump(conn, "projects")
    state = ensure_db_migrated(v39_state)
    assert state.status == "ok", state.message
    with _open(path) as conn:
        assert get_schema_version(conn) == db_models.CURRENT_SCHEMA_VERSION >= 40
        hosts = [dict(r) for r in conn.execute("SELECT * FROM hosts")]
        sessions_after, projects_after = _dump(conn, "sessions"), _dump(conn, "projects")
        trail = conn.execute(
            "SELECT status, backup_path, backup_verified FROM migration_trail "
            "WHERE from_version = '39' AND to_version = ?",
            (str(db_models.CURRENT_SCHEMA_VERSION),)).fetchall()
    assert [(h["key"], h["label"], h["ssh_target"], h["socket"], h["enabled"], h["probe_state"])
            for h in hosts] == [("local", "this machine", None, None, 1, "never")]
    assert len(sessions_after) == len(sessions_before) == 7
    assert {r["host_key"] for r in sessions_after} == {"local"}
    assert {r["host_key"] for r in projects_after} == {"local"}
    assert [{k: v for k, v in r.items() if k != "host_key"} for r in sessions_after] == sessions_before
    assert [{k: v for k, v in r.items() if k != "host_key"} for r in projects_after] == projects_before
    status, backup_path, verified = trail[-1]
    assert status.startswith("completed") and verified == 1 and "bak-v39" in backup_path
    assert list(v39_state.rglob(backup_path)), "the recorded backup is not on disk"


def test_the_identity_index_is_the_quad_and_the_triple_is_gone(v39_state):
    assert ensure_db_migrated(v39_state).status == "ok"
    with _open(db_path_for(v39_state)) as conn:
        assert _index_sql(conn, TRIPLE_INSTANCE_INDEX) is None
        assert _index_sql(conn, HOST_INSTANCE_INDEX) == (
            "CREATE UNIQUE INDEX ux_sessions_host_instance ON sessions "
            "(host_key, tmux_socket, tmux_name, tmux_created_epoch) "
            "WHERE tmux_name IS NOT NULL AND tmux_created_epoch IS NOT NULL")


def _duplicate_of_running(conn, host_key: str) -> None:
    conn.execute(
        "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, origin, "
        "lifecycle, host_key, created_at, updated_at) VALUES (?, 'carnivore', 'carnivore_api', "
        "1790000200, 'observed', 'running', ?, ?, ?)", (f"dup-{host_key}", host_key, STAMP, STAMP))


def test_local_rows_still_collide_on_the_quad_and_other_hosts_do_not(v39_state):
    assert ensure_db_migrated(v39_state).status == "ok"
    with _open(db_path_for(v39_state)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            _duplicate_of_running(conn, "local")
        _duplicate_of_running(conn, "hosta")
        assert conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE tmux_name = 'carnivore_api' "
            "AND tmux_created_epoch = 1790000200").fetchone()[0] == 2


def test_the_collision_comes_from_the_quad_index(v39_state):
    assert ensure_db_migrated(v39_state).status == "ok"
    with _open(db_path_for(v39_state)) as conn:
        conn.execute(f"DROP INDEX {HOST_INSTANCE_INDEX}")
        _duplicate_of_running(conn, "local")
        assert conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE host_key = 'local' AND tmux_name = 'carnivore_api' "
            "AND tmux_created_epoch = 1790000200").fetchone()[0] == 2


def test_the_step_is_idempotent_and_finishes_a_partial_application():
    conn = sqlite3.connect(":memory:")
    conn.execute("BEGIN")
    for version in range(0, 39):
        STEPS[version](conn)
    conn.execute(V40_COLUMNS[0][2])
    STEPS[39](conn)
    STEPS[39](conn)
    assert conn.execute("SELECT key FROM hosts").fetchall() == [("local",)]
    for table in ("sessions", "projects"):
        assert "host_key" in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    assert _index_sql(conn, HOST_INSTANCE_INDEX) is not None
    assert _index_sql(conn, TRIPLE_INSTANCE_INDEX) is None


def test_the_step_is_audited_partitioned_and_its_reversal_declared():
    assert UNGATED_VERSION_DDL[40] == DDL_V40
    assert UNGATED_VERSION_COLUMNS[40] == V40_COLUMNS
    assert TRIPLE_INSTANCE_INDEX in SUPERSEDED_OBJECTS
    assert side_for_table("hosts") == SIDE_APP
    assert db_models.REVERSAL_SQL_V40 == REVERSAL_SQL_V40
    assert db_models.REVERSAL_DESTROYS[40] == ("hosts (whole table)",)
    assert REVERSAL_SQL_V40[1] == db_models.DDL_SESSIONS_INSTANCE_INDEX


def _chain(skip=()) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("BEGIN")
    for version in range(0, db_models.CURRENT_SCHEMA_VERSION):
        if version not in skip:
            STEPS[version](conn)
    conn.commit()
    return conn


def test_a_healthy_chain_audits_clean_without_demanding_the_triple():
    audit = audit_schema(_chain(), db_models.CURRENT_SCHEMA_VERSION)
    assert audit.status == AUDIT_OK, audit.missing_names
    assert audit.checked > 0


def test_a_crossed_key_40_is_caught_and_repaired_columns_before_the_index():
    conn = _chain(skip=(39,))
    audit = audit_schema(conn, db_models.CURRENT_SCHEMA_VERSION)
    assert audit.status == AUDIT_MISSING
    later_host_columns = {
        f"{table}.{column}"
        for version, columns in UNGATED_VERSION_COLUMNS.items() if version > 40
        for table, column, _statement in columns if table == "hosts"
    }
    assert set(audit.missing_names) == {
        "hosts", "sessions.host_key", "projects.host_key", HOST_INSTANCE_INDEX,
        *later_host_columns,
    }
    conn.execute("BEGIN")
    created = repair_missing(conn, audit.missing)
    conn.commit()
    assert created.index(HOST_INSTANCE_INDEX) > created.index("sessions.host_key")
    assert audit_schema(conn, db_models.CURRENT_SCHEMA_VERSION).status == AUDIT_OK


def test_the_reversal_restores_the_triple_and_drops_hosts(v39_state):
    assert ensure_db_migrated(v39_state).status == "ok"
    with _open(db_path_for(v39_state)) as conn:
        for statement in REVERSAL_SQL_V40:
            conn.execute(statement)
        assert _index_sql(conn, TRIPLE_INSTANCE_INDEX) is not None
        assert _index_sql(conn, HOST_INSTANCE_INDEX) is None
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'hosts'").fetchone() is None


def test_table_columns_cached_and_invalidated_by_schema_change(tmp_path):
    from src.core.db import column_exists
    from src.core.hosts.ddl import _columns

    path = tmp_path / "t.db"
    with closing(sqlite3.connect(path, isolation_level=None)) as conn:
        conn.execute("CREATE TABLE widgets (id INTEGER)")
        statements: List[str] = []
        conn.set_trace_callback(statements.append)
        assert column_exists(conn, "widgets", "id")
        assert _columns(conn, "widgets") == {"id"}
        statements.clear()
        assert column_exists(conn, "widgets", "id")
        assert not column_exists(conn, "widgets", "extra")
        assert _columns(conn, "widgets") == {"id"}
        assert not [s for s in statements if "table_info" in s]
        with closing(sqlite3.connect(path)) as other:
            other.execute("ALTER TABLE widgets ADD COLUMN extra TEXT")
            other.commit()
        assert column_exists(conn, "widgets", "extra")
        assert _columns(conn, "widgets") == {"id", "extra"}

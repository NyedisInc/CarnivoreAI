
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import CURRENT_SCHEMA_VERSION, META_SCHEMA_VERSION
from src.core.db_schema_audit import AUDIT_MISSING, AUDIT_OK, UNGATED_VERSION_DDL, audit_schema
from src.core.db_steps import STEPS, run_chain
from src.core.exports import ddl

TABLES = {"export_bundles", "export_pointers"}
INDEXES = {"ix_export_bundles_project", "ix_export_bundles_session", "ix_export_pointers_bundle"}


def _objects(conn: sqlite3.Connection) -> set:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}


def _v92(state_dir: Path) -> Path:
    path = db_path_for(state_dir)
    with closing(connect(path)) as conn:
        with conn:
            run_chain(conn, 0, 92)
            conn.execute("INSERT INTO sessions (session_uuid, working_dir, origin, created_at, updated_at) VALUES "
                         "('s-1', '/w', 'created', '2026-10-12T00:00:00Z', '2026-10-12T00:00:00Z')")
    return path


def test_the_migrator_backs_up_first_then_adds_both_tables_and_touches_nothing_else(tmp_path: Path) -> None:
    path = _v92(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        assert not TABLES & _objects(conn)
        before = conn.execute("SELECT session_uuid, working_dir FROM sessions").fetchall()
    state = ensure_db_migrated(tmp_path)
    assert state.status == "ok" and CURRENT_SCHEMA_VERSION >= 93
    [backup] = list(tmp_path.glob("*.bak-v92-*"))
    with closing(sqlite3.connect(backup)) as conn:
        assert not TABLES & _objects(conn)
    with closing(sqlite3.connect(path)) as conn:
        assert TABLES | INDEXES <= _objects(conn)
        assert conn.execute("SELECT session_uuid, working_dir FROM sessions").fetchall() == before
        assert conn.execute("SELECT value FROM meta WHERE key = ?", (META_SCHEMA_VERSION,)).fetchone()[0] == str(CURRENT_SCHEMA_VERSION)
    assert ensure_db_migrated(tmp_path).status == "ok" and len(list(tmp_path.glob("*.bak-v92-*"))) == 1


def test_a_fresh_database_walked_zero_to_93_has_the_tables_and_enforces_their_checks() -> None:
    conn = sqlite3.connect(":memory:")
    run_chain(conn, 0, 93)
    assert TABLES | INDEXES <= _objects(conn)
    ok = ("b-1", "a" * 64, "session", 1.0, 1.0)
    conn.execute("INSERT INTO export_bundles (bundle_id, sha256, scope, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", ok)
    row = conn.execute("SELECT locations_json, local_removed, verified_at FROM export_bundles").fetchone()
    assert row == ("[]", 0, None)
    for bad in (("b-2", "short", "session", 1.0, 1.0), ("b-3", "a" * 64, "machine", 1.0, 1.0)):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO export_bundles (bundle_id, sha256, scope, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", bad)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO export_bundles (bundle_id, sha256, scope, created_at, updated_at, local_removed) VALUES ('b-4', ?, 'session', 1, 1, 2)", ("a" * 64,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO export_pointers (conversation_id, family, bundle_id, exported_at) VALUES ('c', 'gemini', 'b-1', 1)")
    conn.execute("INSERT INTO export_pointers (conversation_id, family, bundle_id, exported_at) VALUES ('c', 'claude', 'b-1', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO export_pointers (conversation_id, family, bundle_id, exported_at) VALUES ('c', 'claude', 'b-2', 2)")


def test_apply_v93_alone_is_idempotent_and_the_step_is_registered() -> None:
    conn = sqlite3.connect(":memory:")
    ddl.apply_v93(conn)
    ddl.apply_v93(conn)
    assert TABLES | INDEXES <= _objects(conn)
    assert 92 in STEPS and UNGATED_VERSION_DDL[93] == ddl.DDL_V93


def test_the_schema_audit_knows_the_new_objects_and_can_see_one_missing(tmp_path: Path) -> None:
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        assert audit_schema(conn, 93).status == AUDIT_OK
        conn.execute("DROP TABLE export_pointers")
        report = audit_schema(conn, 93)
        assert report.status == AUDIT_MISSING and "export_pointers" in report.missing_names


from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core import db_models
from src.core.db import connect, db_path_for, get_schema_version, set_meta
from src.core.db_migration import ensure_db_migrated
from src.core.db_schema_audit import AUDIT_OK, audit_schema
from src.core.db_steps import STEPS
from src.core.launch_profiles.ddl import apply_v56

STAMP = "2026-10-02T10:00:00.000000Z"


def _open(path: Path):
    return closing(connect(path, create=False))


def _column(conn, name: str):
    return next((r for r in conn.execute("PRAGMA table_info(sessions)") if r[1] == name), None)


@pytest.fixture()
def v55_state(tmp_path) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    assert ensure_db_migrated(state_dir).status == "ok"
    with _open(db_path_for(state_dir)) as conn:
        conn.execute("ALTER TABLE sessions DROP COLUMN launch_record")
        conn.execute(
            "INSERT INTO sessions (session_uuid, origin, created_at, updated_at) VALUES ('u-1', 'created', ?, ?)", (STAMP, STAMP))
        set_meta(conn, db_models.META_SCHEMA_VERSION, "55")
    return state_dir


def test_a_v55_datastore_migrates_to_v56_with_a_nullable_column_and_null_rows(v55_state):
    path = db_path_for(v55_state)
    with _open(path) as conn:
        assert get_schema_version(conn) == 55 and _column(conn, "launch_record") is None
    assert 55 in STEPS and db_models.CURRENT_SCHEMA_VERSION >= 56
    state = ensure_db_migrated(v55_state)
    assert state.status == "ok", state.message
    with _open(path) as conn:
        assert get_schema_version(conn) == db_models.CURRENT_SCHEMA_VERSION
        col = _column(conn, "launch_record")
        assert col is not None and col[2] == "TEXT" and col[3] == 0 and col[4] is None
        assert conn.execute("SELECT launch_record FROM sessions WHERE session_uuid = 'u-1'").fetchone()[0] is None


def test_migrating_twice_is_a_no_op_and_the_audit_passes(v55_state):
    ensure_db_migrated(v55_state)
    with _open(db_path_for(v55_state)) as conn:
        apply_v56(conn)
        before = [tuple(r) for r in conn.execute("PRAGMA table_info(sessions)")]
        apply_v56(conn)
        assert [tuple(r) for r in conn.execute("PRAGMA table_info(sessions)")] == before
        assert audit_schema(conn, db_models.CURRENT_SCHEMA_VERSION).status == AUDIT_OK
    assert ensure_db_migrated(v55_state).status == "ok"

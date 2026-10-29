
from __future__ import annotations

import os
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain


def _insert_raw_session(
    conn, *, uuid: str, name: str, claude_uuid, claude_uuid_source=None
) -> None:
    conn.execute(
        "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, "
        "origin, agent_family_source, claude_session_uuid, lifecycle, "
        "project_attribution, created_at, updated_at) "
        "VALUES (?, 'cloude', ?, 'created', 'unknown', ?, 'unknown', "
        "'unknown', '2027-01-01T00:00:00Z', '2027-01-01T00:00:00Z')",
        (uuid, name, claude_uuid),
    )


def test_v13_reached_and_current(tmp_path):
    state = ensure_db_migrated(tmp_path, 4, "0.8.2")
    assert state.status == "ok"
    assert state.schema_version == CURRENT_SCHEMA_VERSION
    assert CURRENT_SCHEMA_VERSION >= 13


def test_column_exists_after_migration(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    assert "claude_session_uuid_source" in cols


def test_existing_uuid_rows_are_backfilled_as_hook(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, 12)
        _insert_raw_session(
            conn, uuid="row-a", name="a", claude_uuid="claude-uuid-a"
        )
        conn.commit()

        with conn:
            run_chain(conn, 12, CURRENT_SCHEMA_VERSION)

        row = conn.execute(
            "SELECT claude_session_uuid_source FROM sessions WHERE tmux_name = 'a'"
        ).fetchone()
    assert row["claude_session_uuid_source"] == "hook"


def test_null_uuid_rows_stay_null_source(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, 12)
        _insert_raw_session(conn, uuid="row-b", name="b", claude_uuid=None)
        conn.commit()

        with conn:
            run_chain(conn, 12, CURRENT_SCHEMA_VERSION)

        row = conn.execute(
            "SELECT claude_session_uuid, claude_session_uuid_source "
            "FROM sessions WHERE tmux_name = 'b'"
        ).fetchone()
    assert row["claude_session_uuid"] is None
    assert row["claude_session_uuid_source"] is None


def test_migration_is_idempotent(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, 13)
        _insert_raw_session(
            conn, uuid="row-c", name="c", claude_uuid="claude-uuid-c"
        )
        conn.execute(
            "UPDATE sessions SET claude_session_uuid_source = 'correlated' "
            "WHERE tmux_name = 'c'"
        )
        conn.commit()

        with conn:
            run_chain(conn, 12, 13)

        row = conn.execute(
            "SELECT claude_session_uuid_source FROM sessions WHERE tmux_name = 'c'"
        ).fetchone()
    assert row["claude_session_uuid_source"] == "correlated"

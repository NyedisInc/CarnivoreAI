
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_dbmig_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_dbmig_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.db import (
    column_exists,
    connect,
    db_path_for,
    get_schema_version,
    set_meta,
    transaction,
)


def schema_version_on_disk(state_dir: Path) -> int:
    with closing(connect(db_path_for(state_dir), create=False)) as conn:
        return get_schema_version(conn)


class TwoAlterStep:

    def __init__(self) -> None:
        self.explode = True
        self.calls = 0

    def __call__(self, conn: sqlite3.Connection) -> None:
        self.calls += 1
        if not column_exists(conn, "meta", "note_a"):
            conn.execute("ALTER TABLE meta ADD COLUMN note_a TEXT")
        if self.explode:
            raise RuntimeError("injected crash between the two ALTERs")
        if not column_exists(conn, "meta", "note_b"):
            conn.execute("ALTER TABLE meta ADD COLUMN note_b TEXT")


def drop_meta_columns(state_dir: Path) -> None:
    with closing(connect(db_path_for(state_dir))) as conn:
        with transaction(conn):
            rows = conn.execute("SELECT key, value FROM meta").fetchall()
            conn.execute("DROP TABLE meta")
            conn.execute(
                "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                [(r[0], r[1]) for r in rows],
            )


def reset_to_v1(state_dir: Path) -> None:
    drop_meta_columns(state_dir)
    with closing(connect(db_path_for(state_dir))) as conn:
        with transaction(conn):
            set_meta(conn, "schema_version", "1")


def trail_rows(state_dir: Path) -> list:
    with closing(connect(db_path_for(state_dir), create=False)) as conn:
        return [
            tuple(r)
            for r in conn.execute(
                "SELECT entry_uuid, kind, status FROM migration_trail ORDER BY id"
            ).fetchall()
        ]

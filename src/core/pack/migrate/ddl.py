
from __future__ import annotations

import sqlite3
from typing import Tuple

MIGRATION_STATES: Tuple[str, ...] = ("planned", "applying", "verifying", "flipped", "failed", "moved_back")

DDL_PACK_MIGRATE: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS pack_migrations (
        id                TEXT PRIMARY KEY,
        kind              TEXT NOT NULL CHECK (kind IN ('project', 'company')),
        role              TEXT NOT NULL DEFAULT 'source' CHECK (role IN ('source', 'target')),
        parent_id         TEXT,
        subject_uid       TEXT NOT NULL,
        source_install_id TEXT NOT NULL,
        target_install_id TEXT NOT NULL,
        plan_fingerprint  TEXT,
        state             TEXT NOT NULL CHECK (state IN ('planned', 'applying', 'verifying', 'flipped', 'failed', 'moved_back')),
        step              TEXT,
        manifest_json     TEXT,
        detail_json       TEXT,
        started_at        TEXT NOT NULL,
        finished_at       TEXT,
        error_code        TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS pack_migrations_subject ON pack_migrations(subject_uid, started_at)",
)


def apply_pack_migrate(conn: sqlite3.Connection) -> None:
    for statement in DDL_PACK_MIGRATE:
        conn.execute(statement)


from __future__ import annotations

import sqlite3
from typing import Tuple

BLOB_KINDS: Tuple[str, ...] = ("bundle", "tar", "transcripts", "memory", "manifest")
BLOB_STATES: Tuple[str, ...] = ("receiving", "sealed", "expired")

DDL_PACK_TRANSPORT: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS pack_bundle_tips (
        project_uid  TEXT NOT NULL,
        install_id   TEXT NOT NULL,
        direction    TEXT NOT NULL DEFAULT 'out' CHECK (direction IN ('out', 'in')),
        last_tip_sha TEXT NOT NULL,
        at           TEXT NOT NULL,
        PRIMARY KEY (project_uid, install_id, direction)
    )""",
    """CREATE TABLE IF NOT EXISTS pack_blobs (
        blob_id         TEXT PRIMARY KEY,
        peer_install_id TEXT NOT NULL,
        direction       TEXT NOT NULL CHECK (direction IN ('in', 'out')),
        kind            TEXT,
        size            INTEGER NOT NULL DEFAULT 0,
        sha256          TEXT,
        state           TEXT NOT NULL DEFAULT 'receiving' CHECK (state IN ('receiving', 'sealed', 'expired')),
        path            TEXT,
        created_at      TEXT NOT NULL
    )""",
)


def apply_pack_transport(conn: sqlite3.Connection) -> None:
    for statement in DDL_PACK_TRANSPORT:
        conn.execute(statement)

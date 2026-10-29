
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.tmux_listing import TmuxListing

TEST_SOCKET = "cloudes7test"


def migrated_connection(state_dir: Path) -> sqlite3.Connection:
    ensure_db_migrated(state_dir, 4, "0.8.2")
    return connect(db_path_for(state_dir))


def listing_of(rows: List[Dict[str, Any]]) -> TmuxListing:
    return TmuxListing(ok=True, sessions=list(rows), reason=None)


def listing_row(
    name: str,
    epoch: int,
    *,
    working_dir: Optional[str] = None,
    tmux_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "name": name,
        "created_at_epoch": epoch,
        "window_count": 1,
        "created_by_cloude": False,
        "working_dir": working_dir,
        "tmux_session_id": tmux_session_id,
    }


def listing_unavailable(reason: str = "timeout") -> TmuxListing:
    return TmuxListing.unavailable(reason, detail="probe did not run")


def insert_project(
    conn: sqlite3.Connection, root: str, name: str, *, raw_path: Optional[str] = None
) -> int:
    cursor = conn.execute(
        "INSERT INTO projects (root, raw_path, display_name, source, "
        "presence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (root, raw_path or root, name, "config_import", "unchecked",
         "2026-08-18T00:00:00Z", "2026-08-18T00:00:00Z"),
    )
    return int(cursor.lastrowid)


def session_row(conn: sqlite3.Connection, name: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM sessions WHERE tmux_name = ?", (name,)
    ).fetchone()
    return dict(row) if row is not None else None

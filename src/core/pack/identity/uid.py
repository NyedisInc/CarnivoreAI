
from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Dict, Optional

from src.core.db import table_exists


def new_uid() -> str:
    return uuid.uuid4().hex


def _has_uid(conn: sqlite3.Connection, table: str) -> bool:
    return table_exists(conn, table) and any(r[1] == "uid" for r in conn.execute(f"PRAGMA table_info({table})"))


def project_uid(conn: sqlite3.Connection, project_id: Optional[int]) -> Optional[str]:
    if project_id is None or not _has_uid(conn, "projects"):
        return None
    row = conn.execute("SELECT uid FROM projects WHERE id = ?", (project_id,)).fetchone()
    return row[0] if row else None


def company_uid(conn: sqlite3.Connection, company_id: Optional[int]) -> Optional[str]:
    if company_id is None or not _has_uid(conn, "companies"):
        return None
    row = conn.execute("SELECT uid FROM companies WHERE id = ?", (company_id,)).fetchone()
    return row[0] if row else None


def project_by_uid(conn: sqlite3.Connection, uid: str) -> Optional[Dict[str, Any]]:
    if not uid or not _has_uid(conn, "projects"):
        return None
    row = conn.execute("SELECT * FROM projects WHERE uid = ?", (uid,)).fetchone()
    return dict(row) if row else None


def company_by_uid(conn: sqlite3.Connection, uid: str) -> Optional[Dict[str, Any]]:
    if not uid or not _has_uid(conn, "companies"):
        return None
    row = conn.execute("SELECT * FROM companies WHERE uid = ?", (uid,)).fetchone()
    return dict(row) if row else None

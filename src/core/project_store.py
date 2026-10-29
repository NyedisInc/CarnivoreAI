
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol

import structlog

from src.core.db import get_meta, set_meta, table_exists, transaction
from src.core.db_models import (
    META_IMPORTED_FROM_JSON_RESULT,
    PROJECT_SOURCE_CONFIG_IMPORT,
)
from src.core.project_presence import PresenceResult, check_presence
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

PROJECTS_TABLE = "projects"


class ProjectConfigLike(Protocol):

    name: str
    path: str
    description: Optional[str]
    agent_type: str


@dataclass(frozen=True)
class ImportResult:

    imported: int
    dropped: List[Dict[str, Any]] = field(default_factory=list)


def normalize_root(raw_path: str) -> str:
    return str(Path(raw_path).expanduser())


def _record_import_result(conn: sqlite3.Connection, patch: Dict[str, Any]) -> None:
    raw = get_meta(conn, META_IMPORTED_FROM_JSON_RESULT)
    try:
        existing = json.loads(raw) if raw else {}
        if not isinstance(existing, dict):
            existing = {}
    except (TypeError, ValueError):
        existing = {}
    existing.update(patch)
    set_meta(conn, META_IMPORTED_FROM_JSON_RESULT, json.dumps(existing, sort_keys=True))


def import_from_config(
    conn: sqlite3.Connection,
    projects: Iterable[ProjectConfigLike],
    *,
    now: Optional[str] = None,
) -> ImportResult:
    stamp = now or utc_now()
    existing_roots = {
        row[0] for row in conn.execute("SELECT root FROM projects").fetchall()
    }
    dropped: List[Dict[str, Any]] = []
    imported = 0

    for cfg in projects:
        root = normalize_root(cfg.path)
        if root in existing_roots:
            dropped.append(
                {
                    "name": cfg.name,
                    "raw_path": cfg.path,
                    "root": root,
                    "reason": "duplicate_root",
                }
            )
            continue
        existing_roots.add(root)
        conn.execute(
            "INSERT INTO projects (root, raw_path, display_name, description, "
            "default_agent_type, source, presence, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'unchecked', ?, ?)",
            (
                root,
                cfg.path,
                cfg.name,
                cfg.description,
                cfg.agent_type,
                PROJECT_SOURCE_CONFIG_IMPORT,
                stamp,
                stamp,
            ),
        )
        imported += 1

    if dropped:
        _record_import_result(
            conn, {"projects_duplicate_roots_dropped": dropped}
        )

    return ImportResult(imported=imported, dropped=dropped)


def list_projects(
    conn: sqlite3.Connection, *, include_archived: bool = False
) -> List[Dict[str, Any]]:
    if not table_exists(conn, PROJECTS_TABLE):
        return []
    query = "SELECT * FROM projects"
    if not include_archived:
        query += " WHERE archived_at IS NULL"
    query += " ORDER BY id DESC"
    return [dict(row) for row in conn.execute(query).fetchall()]


def get_project_by_root(
    conn: sqlite3.Connection, root: str
) -> Optional[Dict[str, Any]]:
    if not table_exists(conn, PROJECTS_TABLE):
        return None
    row = conn.execute(
        "SELECT * FROM projects WHERE root = ?", (root,)
    ).fetchone()
    return dict(row) if row is not None else None


def _apply_presence(
    conn: sqlite3.Connection, project_id: int, result: PresenceResult
) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE projects SET presence = ?, presence_detail = ?, "
            "presence_checked_at = ?, updated_at = ? WHERE id = ?",
            (
                result.presence,
                result.detail,
                result.checked_at,
                result.checked_at,
                project_id,
            ),
        )


def refresh_and_list_presence(
    conn: sqlite3.Connection, *, stat_fn=None
) -> List[Dict[str, Any]]:
    rows = list_projects(conn, include_archived=True)
    updated: List[Dict[str, Any]] = []
    for row in rows:
        result = check_presence(row["root"], stat_fn=stat_fn)
        try:
            _apply_presence(conn, row["id"], result)
        except sqlite3.Error as exc:
            logger.warning(
                "project_presence_write_failed",
                project_id=row["id"],
                error=str(exc),
            )
        row = dict(row)
        row["presence"] = result.presence
        row["presence_detail"] = result.detail
        row["presence_checked_at"] = result.checked_at
        updated.append(row)
    return updated

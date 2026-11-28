from __future__ import annotations

import sqlite3
from typing import Dict, List, Tuple

import structlog

from src.core.db import table_exists
from src.core.library_cleanup.errors import CleanupRefused

logger = structlog.get_logger()

REFUSE_STORAGE_CONFLICT = "storage_conflict"
REFUSE_SWARM_OR_PACK = "source_has_swarm_or_pack_data"
REFUSE_TASK_MANAGER = "source_has_task_manager_data"

TASK_MANAGER_KEY_COLUMNS: Tuple[str, ...] = ("list_key", "project_key")

MOVED_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("transcript_archives", "project_id"),
    ("transcript_root_decisions", "project_id"),
    ("companies", "hq_project_id"),
)

REFUSED_BY_ID: Tuple[Tuple[str, str], ...] = (
    ("swarm_agents", "project_id"),
    ("swarm_promotions", "project_id"),
    ("swarm_project_settings", "project_id"),
    ("swarm_suggestions", "made_project_id"),
)

REFUSED_BY_UID: Tuple[Tuple[str, str], ...] = (
    ("swarm_remote_bodies", "project_uid"),
    ("project_replicas", "project_uid"),
    ("pack_bundle_tips", "project_uid"),
    ("pack_carried_trust", "project_uid"),
    ("export_bundles", "project_uid"),
)

REFUSED_WHEN_PRESENT: Tuple[Tuple[str, str], ...] = REFUSED_BY_ID + REFUSED_BY_UID

LEFT_ALONE: Dict[str, str] = {
    "installed_items": "project_path is a folder path, not a project row id",
    "pack_rollups": "project is a peer machine's opaque hash of ITS project, never this machine's row id",
    "pack_rollups_5m": "project is a peer machine's opaque hash of ITS project, never this machine's row id",
    "pack_rollup_activity": "project is a peer machine's opaque hash of ITS project, never this machine's row id",
    "pack_rollup_conversations": "project is a peer machine's opaque hash of ITS project, never this machine's row id",
    "pack_rollup_counters": "project is a peer machine's opaque hash of ITS project, never this machine's row id",
    "pack_rollup_projects": "project is a peer machine's opaque hash of ITS project (name beside it), never this machine's row id",
    "work_write_actors": "cross_project is a yes/no flag on a write, not a project id",
    "message_transcripts": "dormant archive schema; project_id references message_projects (a corpus slug, its own id space), history only, read by nothing that acts on a project",
    "message_projects": "dormant archive schema: a corpus-and-slug record of where Claude wrote, never this machine's project row",
    "usage_minute": "stats store (stats.db): project is a dim_project id, an opaque hash of a folder (extract.project_key, read by stats/rollup.py:214), never a project row id; history only",
    "usage_hour": "stats store: project is a dim_project id (a folder hash), never a project row id",
    "counter_minute": "stats store: project is a dim_project id (a folder hash), never a project row id",
    "counter_hour": "stats store: project is a dim_project id (a folder hash), never a project row id",
    "stats_git_progress": "stats store: project is the opaque folder hash (extract.project_key) of a git history read; history only",
    "stats_git_markers": "stats store: project is the opaque folder hash (extract.project_key) of a git history read; history only",
    "dim_live": "stats store: project is a dim_project id (a folder hash)",
    "conversation_index_fts": "a search shadow of conversation_index, rebuilt by its own triggers",
}

MOVED_BY_MERGE: Tuple[str, ...] = ("sessions", "conversation_index", "project_storage", "work_items")

WORK_ITEMS = "work_items"


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return table_exists(conn, table) and column in {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def _count(conn: sqlite3.Connection, table: str, column: str, value: object) -> int:
    if not _has_column(conn, table, column):
        return 0
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" = ?', (value,)).fetchone()[0])  # noqa: S608


def task_manager_tables(conn: sqlite3.Connection) -> Dict[str, Tuple[str, ...]]:
    found: Dict[str, Tuple[str, ...]] = {}
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'work\\_%' ESCAPE '\\'").fetchall():
        cols = tuple(r[1] for r in conn.execute(f'PRAGMA table_info("{table}")') if r[1] in TASK_MANAGER_KEY_COLUMNS)
        if cols:
            found[table] = cols
    return found


def refuse_if_blocked(conn: sqlite3.Connection, source_id: int, target_id: int) -> None:
    row = conn.execute("SELECT uid FROM projects WHERE id = ?", (source_id,)).fetchone()
    uid = row[0] if row else None
    found: List[str] = []
    for table, column in REFUSED_BY_ID:
        if n := _count(conn, table, column, source_id):
            found.append(f"{table}={n}")
    for table, column in REFUSED_BY_UID:
        if uid and (n := _count(conn, table, column, uid)):
            found.append(f"{table}={n}")
    if found:
        raise CleanupRefused(REFUSE_SWARM_OR_PACK,
                             "the source project has swarm or pack data this merge does not move: " + ", ".join(found))
    tm = [f"{t}={n}" for t, cols in task_manager_tables(conn).items() for c in cols
          if (n := _count(conn, t, c, str(source_id)))]
    if tm:
        raise CleanupRefused(REFUSE_TASK_MANAGER, "the source project has task manager data this merge does not move: " + ", ".join(tm))
    if _count(conn, "project_storage", "project_id", source_id) and _count(conn, "project_storage", "project_id", target_id):
        raise CleanupRefused(REFUSE_STORAGE_CONFLICT,
                             "both projects already have a storage record; resolve one before merging")


def repoint_dependents(conn: sqlite3.Connection, source_id: int, target_id: int, target_name: str) -> None:
    for table, column in (*MOVED_COLUMNS, ("project_storage", "project_id")):
        if not _has_column(conn, table, column):
            logger.debug("library_project_dependents_table_skipped", table=table, column=column)
            continue
        conn.execute(f'UPDATE "{table}" SET "{column}" = ? WHERE "{column}" = ?', (target_id, source_id))  # noqa: S608
    if _count(conn, WORK_ITEMS, "from_project_id", str(source_id)):
        conn.execute("UPDATE work_items SET from_project_id = ?, from_project_name = ? WHERE from_project_id = ?",
                     (str(target_id), target_name, str(source_id)))
    logger.info("library_project_dependents_moved", source_id=source_id, target_id=target_id)

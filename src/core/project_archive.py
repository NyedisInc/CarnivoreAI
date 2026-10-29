
from __future__ import annotations

import sqlite3
from typing import Optional

import structlog

from src.core import resource_push
from src.core.resource_push import topics as resource_topics

from src.core.companion_shell.ddl import COMPANION_OF_COLUMN
from src.core import session_store
from src.core.db import column_exists, transaction
from src.core.project_writes import ProjectNotFound
from src.core.trail_entry import utc_now

logger = structlog.get_logger()


def archive_project(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    now: Optional[str] = None,
) -> bool:
    stamp = now or utc_now()

    with transaction(conn):
        row = conn.execute(
            "SELECT archived_at FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise ProjectNotFound(str(project_id))
        if row["archived_at"] is not None:
            return False
        conn.execute(
            "UPDATE projects SET archived_at = ?, updated_at = ? "
            "WHERE id = ? AND archived_at IS NULL",
            (stamp, stamp, project_id),
        )

    logger.info("project_archived", project_id=project_id, archived_at=stamp)
    resource_push.notify(resource_topics.PROJECTS)
    return True


def unarchive_project(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    now: Optional[str] = None,
) -> bool:
    stamp = now or utc_now()

    with transaction(conn):
        row = conn.execute(
            "SELECT archived_at FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise ProjectNotFound(str(project_id))
        if row["archived_at"] is None:
            return False
        conn.execute(
            "UPDATE projects SET archived_at = NULL, updated_at = ? "
            "WHERE id = ? AND archived_at IS NOT NULL",
            (stamp, project_id),
        )

    logger.info("project_unarchived", project_id=project_id, at=stamp)
    resource_push.notify(resource_topics.PROJECTS)
    return True




_LIVE_LIFECYCLE = "running"


def _project_archive_stamp(conn: sqlite3.Connection, project_id: int) -> Optional[str]:
    row = conn.execute("SELECT archived_at FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ProjectNotFound(str(project_id))
    return row["archived_at"]


def archive_project_and_sessions(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    now: Optional[str] = None,
) -> dict:
    changed = archive_project(conn, project_id, now=now)
    stamp = _project_archive_stamp(conn, project_id)
    archived = live = 0
    if session_store.sessions_table_ready(conn):
        companion_col = COMPANION_OF_COLUMN if column_exists(conn, "sessions", COMPANION_OF_COLUMN) else "NULL"
        rows = conn.execute(
            f"SELECT session_uuid, lifecycle, {companion_col} AS companion FROM sessions "
            "WHERE project_id = ? AND archived_at IS NULL",
            (project_id,),
        ).fetchall()
        for row in rows:
            if row["lifecycle"] == _LIVE_LIFECYCLE:
                live += row["companion"] is None
            elif session_store.archive_session(conn, row["session_uuid"], now=stamp):
                archived += 1
    logger.info(
        "project_sessions_archived",
        project_id=project_id,
        sessions_archived=archived,
        sessions_live=live,
    )
    if archived:
        resource_push.notify(resource_topics.PROJECTS)
    return {"changed": changed, "archived_at": stamp, "sessions_archived": archived, "sessions_live": live}


def unarchive_project_and_sessions(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    now: Optional[str] = None,
) -> dict:
    stamp = _project_archive_stamp(conn, project_id)
    changed = unarchive_project(conn, project_id, now=now)
    restored = 0
    if stamp is not None and session_store.sessions_table_ready(conn):
        rows = conn.execute(
            "SELECT session_uuid FROM sessions WHERE project_id = ? AND archived_at = ?",
            (project_id, stamp),
        ).fetchall()
        for row in rows:
            if session_store.unarchive_session(conn, row["session_uuid"], now=now):
                restored += 1
    logger.info("project_sessions_restored", project_id=project_id, sessions_restored=restored)
    if restored:
        resource_push.notify(resource_topics.PROJECTS)
    return {"changed": changed, "sessions_restored": restored}

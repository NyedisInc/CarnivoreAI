
from __future__ import annotations

import re
import sqlite3
from typing import MutableSet, Optional

import structlog

from src.core.db_models import PROJECT_SOURCE_USER, SESSION_ATTRIBUTION_DERIVED_DEEPEST
from src.core.hosts.identity import remote_project_root
from src.core.session_project_binding import (
    BINDING_CREATED,
    BINDING_MATCHED,
    BINDING_UNKNOWN,
    ProjectBinding,
    _display_name_for,
)
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

UID_RE = re.compile(r"[0-9a-f]{32}")


def bind_remote_project(conn: sqlite3.Connection, host_key: str, far_dir: str, *,
                        now: Optional[str] = None, root: Optional[str] = None,
                        project_uid: Optional[str] = None, claimed: Optional[MutableSet[int]] = None) -> ProjectBinding:
    root = root or remote_project_root(host_key, far_dir)
    stamp = now or utc_now()
    uid = project_uid if isinstance(project_uid, str) and UID_RE.fullmatch(project_uid) else None
    claimed = claimed if claimed is not None else set()
    try:
        if uid is not None:
            held = conn.execute("SELECT id, root FROM projects WHERE uid = ?", (uid,)).fetchone()
            if held is not None:
                claimed.add(int(held[0]))
                return ProjectBinding(project_id=int(held[0]), attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST,
                                      rule=BINDING_MATCHED, root=held[1])
        found = conn.execute("SELECT id FROM projects WHERE root = ? AND host_key = ?", (root, host_key)).fetchone()
        if found is not None:
            if uid is not None and int(found[0]) not in claimed:
                conn.execute("UPDATE projects SET uid = ? WHERE id = ?", (uid, found[0]))
                claimed.add(int(found[0]))
            return ProjectBinding(project_id=int(found[0]),
                                  attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST,
                                  rule=BINDING_MATCHED, root=root)
        cursor = conn.execute(
            "INSERT INTO projects (root, raw_path, display_name, source, presence, host_key, "
            "created_at, updated_at, last_opened_at, uid) VALUES (?, ?, ?, ?, 'unchecked', ?, ?, ?, ?, ?)",
            (root, root, _display_name_for(root, conn), PROJECT_SOURCE_USER, host_key,
             stamp, stamp, stamp, uid),
        )
        if uid is not None:
            claimed.add(int(cursor.lastrowid))
    except sqlite3.Error as exc:
        logger.warning("remote_project_bind_failed", host=host_key, error=str(exc))
        return ProjectBinding(rule=BINDING_UNKNOWN,
                              detail="the projects table could not be read or written")
    logger.info("remote_project_minted", host=host_key, project_id=int(cursor.lastrowid))
    return ProjectBinding(project_id=int(cursor.lastrowid),
                          attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST,
                          rule=BINDING_CREATED, created_project=True, root=root)

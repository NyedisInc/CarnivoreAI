from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, Optional

import structlog

from src.core.db import transaction
from src.core.library_cleanup.errors import CleanupNotFound, CleanupRefused
from src.core.project_tombstones import record_tombstone

logger = structlog.get_logger()

REFUSE_SAME_PROJECT = "same_project"
REFUSE_DIFFERENT_FOLDER = "different_folder"


def canonical_folder(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    head, tail = os.path.normpath(path), []
    while head and head != os.sep and not os.path.exists(head):
        head, leaf = os.path.split(head)
        tail.append(leaf)
    resolved = os.path.realpath(head) if head else head
    return os.path.join(resolved, *reversed(tail)) if tail else resolved


def _project(conn: sqlite3.Connection, project_id: int) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise CleanupNotFound("no_project", f"no project with id {project_id}")
    cols = [d[0] for d in conn.execute("SELECT * FROM projects LIMIT 0").description]
    return dict(zip(cols, row))


def merge_projects(conn: sqlite3.Connection, source_id: int, target_id: int, *,
                   allow_different_folder: bool = False) -> Dict[str, Any]:
    if source_id == target_id:
        raise CleanupRefused(REFUSE_SAME_PROJECT, "a project cannot be merged into itself")
    with transaction(conn):
        source, target = _project(conn, source_id), _project(conn, target_id)
        same = canonical_folder(source["root"]) == canonical_folder(target["root"])
        if not same and not allow_different_folder:
            raise CleanupRefused(REFUSE_DIFFERENT_FOLDER,
                                 f"{source['root']!r} and {target['root']!r} are different folders")
        moved = conn.execute("UPDATE sessions SET project_id = ? WHERE project_id = ?",
                             (target_id, source_id)).rowcount
        indexed = conn.execute("UPDATE conversation_index SET project_id = ? WHERE project_id = ?",
                               (target_id, source_id)).rowcount
        conn.execute("DELETE FROM projects WHERE id = ?", (source_id,))
        record_tombstone(conn, source["root"], source["display_name"])
    result = {"source": {"id": source_id, "name": source["display_name"], "root": source["root"]},
              "target": {"id": target_id, "name": target["display_name"], "root": target["root"]},
              "sessions_moved": moved, "index_rows_moved": indexed, "same_folder": same}
    logger.info("library_project_merged", source_id=source_id, target_id=target_id,
                sessions_moved=moved, index_rows_moved=indexed, same_folder=same)
    return result

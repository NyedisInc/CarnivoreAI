
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core import resource_push
from src.core.resource_push import topics as resource_topics

from src.core.companies.store import attach_company_names
from src.core.pack.identity.home import attach_machine_labels
from src.core.db import table_exists, transaction
from src.core.db_models import PROJECT_SOURCE_USER
from src.core.project_colors.palette import normalize_color, is_hex_color
from src.core.project_store import PROJECTS_TABLE, normalize_root
from src.core.project_tombstones import clear_tombstone, read_tombstone, record_tombstone
from src.core.session_project_binding import (
    adopt_sessions_under_root,
    matchable_roots,
    fold_path,
    swallows_live_root,
)
from src.core.transcript_import_paths import canonical
from src.core.pack.trust_carry import store as trust_store
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

_ORDER_BY = "ORDER BY (work_at IS NULL) ASC, work_at DESC, id ASC"

_WORK_ROLLUP = (
    "(SELECT MAX(s.last_work_at) FROM sessions s "
    "WHERE s.project_id = projects.id) AS work_at"
)

_ORDER_BY_NO_WORK_COLUMN = "ORDER BY id ASC"


class ProjectWriteError(RuntimeError):
    pass


class ProjectNotFound(ProjectWriteError):
    pass


class ProjectNameAmbiguous(ProjectWriteError):
    pass


class ProjectNameConflict(ProjectWriteError):
    pass


class ProjectColorInvalid(ProjectWriteError):
    pass


class ProjectRootConflict(ProjectWriteError):

    def __init__(
        self,
        message: str,
        existing_id: Optional[int] = None,
        existing_name: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.existing_id = existing_id
        self.existing_name = existing_name


class ProjectRootRefused(ProjectWriteError):

    CODE = "project_root_refused"


def _base_folders() -> List[str]:
    from src.config.settings import NEW_DEFAULT_WORKING_DIR, OLD_DEFAULT_WORKING_DIR, Settings

    raw = [OLD_DEFAULT_WORKING_DIR, NEW_DEFAULT_WORKING_DIR, Settings().default_working_dir]
    return sorted({canonical(os.path.expanduser(r)) or r for r in raw})


def refuse_unsafe_root(conn: sqlite3.Connection, root: str) -> None:
    resolved = canonical(root) or root
    if fold_path(resolved) in {fold_path(b) for b in _base_folders()}:
        raise ProjectRootRefused(f"{root} is the projects base folder, not a project folder")
    if swallows_live_root(resolved, matchable_roots(conn)):
        raise ProjectRootRefused(f"{root} contains other projects, so it cannot be a project itself")


@dataclass(frozen=True)
class ProjectRow:

    id: int
    root: str
    raw_path: str
    name: str
    description: Optional[str]
    agent_type: Optional[str]

    @classmethod
    def from_db(cls, row: Dict[str, Any]) -> "ProjectRow":
        return cls(
            id=row["id"],
            root=row["root"],
            raw_path=row["raw_path"],
            name=row["display_name"],
            description=row["description"],
            agent_type=row["default_agent_type"],
        )


def _work_rollup_available(conn: sqlite3.Connection) -> bool:
    if not table_exists(conn, "sessions"):
        return False
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    return "last_work_at" in cols


def list_projects_ordered(
    conn: sqlite3.Connection, *, include_archived: bool = False
) -> List[Dict[str, Any]]:
    if not table_exists(conn, PROJECTS_TABLE):
        return []
    have_work = _work_rollup_available(conn)
    if have_work:
        query = "SELECT projects.*, " + _WORK_ROLLUP + " FROM projects"
    else:
        query = "SELECT * FROM projects"
    if not include_archived:
        query += " WHERE archived_at IS NULL"
    query += " " + (_ORDER_BY if have_work else _ORDER_BY_NO_WORK_COLUMN)
    rows = [dict(row) for row in conn.execute(query).fetchall()]
    attach_company_names(conn, rows)
    attach_machine_labels(conn, rows)
    if not have_work:
        for row in rows:
            row["work_at"] = None
    return rows


def resolve_by_name(
    conn: sqlite3.Connection, name: str
) -> Dict[str, Any]:
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM projects WHERE display_name = ? ORDER BY id ASC",
            (name,),
        ).fetchall()
    ]
    if not rows:
        raise ProjectNotFound(name)
    if len(rows) > 1:
        local = [r for r in rows if r.get("host_key") == "local"]
        if len(local) == 1:
            return local[0]
        raise ProjectNameAmbiguous(
            f"{len(rows)} projects are named {name!r} "
            f"(roots: {', '.join(r['root'] for r in rows)})"
        )
    return rows[0]


def create_project(
    conn: sqlite3.Connection,
    *,
    name: str,
    path: str,
    description: Optional[str] = None,
    agent_type: Optional[str] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    stamp = now or utc_now()
    root = normalize_root(path)

    with transaction(conn):
        row, _cleared, adopted = insert_project_row(
            conn, root=root, raw_path=path, name=name, uid=None, source=PROJECT_SOURCE_USER,
            description=description, agent_type=agent_type, now=stamp,
        )
    new_id = row["id"]
    logger.info(
        "project_created_in_db",
        project_id=new_id,
        root=root,
        sessions_adopted=len(adopted),
    )
    resource_push.notify(resource_topics.PROJECTS)
    return dict(
        conn.execute("SELECT * FROM projects WHERE id = ?", (new_id,)).fetchone()
    )


def find_root_clash(conn: sqlite3.Connection, root: str) -> Optional[Tuple[str, int]]:
    exact = conn.execute("SELECT display_name, id FROM projects WHERE root = ?", (root,)).fetchone()
    if exact is not None:
        return exact[0], exact[1]
    wanted = fold_path(canonical(root) or root)
    for stored, name, pid in conn.execute("SELECT root, display_name, id FROM projects"):
        if fold_path(canonical(stored) or stored) == wanted:
            return name, pid
    return None


def insert_project_row(
    conn: sqlite3.Connection,
    *,
    root: str,
    raw_path: str,
    name: str,
    uid: Optional[str],
    source: str,
    skip_session_ids: frozenset = frozenset(),
    description: Optional[str] = None,
    agent_type: Optional[str] = None,
    now: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    stamp = now or utc_now()
    refuse_unsafe_root(conn, root)
    clash = find_root_clash(conn, root)
    if clash is not None:
        raise ProjectRootConflict(
            f"a project at {root} already exists, named {clash[0]!r}",
            existing_id=clash[1],
            existing_name=clash[0],
        )
    if conn.execute("SELECT 1 FROM projects WHERE display_name = ? AND host_key = 'local'", (name,)).fetchone():
        raise ProjectNameConflict(f"Project with name '{name}' already exists")
    cursor = conn.execute(
        "INSERT INTO projects (root, raw_path, display_name, description, "
        "default_agent_type, source, presence, created_at, updated_at, "
        "last_opened_at) VALUES (?, ?, ?, ?, ?, ?, 'unchecked', ?, ?, ?)",
        (root, raw_path, name, description, agent_type, source, stamp, stamp, stamp),
    )
    new_id = int(cursor.lastrowid)
    if uid is not None:
        conn.execute("UPDATE projects SET uid = ? WHERE id = ?", (uid, new_id))
    cleared = read_tombstone(conn, root)
    clear_tombstone(conn, root)
    adopted = adopt_sessions_under_root(conn, root=root, project_id=new_id, now=stamp, skip_ids=skip_session_ids)
    row = dict(conn.execute("SELECT * FROM projects WHERE id = ?", (new_id,)).fetchone())
    return row, cleared, adopted


def remove_created_project(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    restore_tombstone: Optional[Dict[str, Any]],
    adopted_ids: List[Dict[str, Any]],
) -> None:
    for entry in adopted_ids:
        conn.execute(
            "UPDATE sessions SET project_id = ?, project_attribution = ? WHERE id = ? AND project_id = ?",
            (entry["from_project_id"], entry["from_attribution"], entry["id"], project_id),
        )
    trust_store.forget_project(conn, project_id)
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    if restore_tombstone is not None:
        conn.execute(
            "INSERT INTO project_tombstones (root, display_name, deleted_at) VALUES (?, ?, ?) ON CONFLICT(root) DO NOTHING",
            (restore_tombstone["root"], restore_tombstone["display_name"], restore_tombstone["deleted_at"]),
        )


def update_project(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    new_name: Optional[str] = None,
    description: Optional[str] = None,
    default_agent_type: Optional[str] = None,
    color: Optional[str] = None,
    now: Optional[str] = None,
    short_description: Optional[str] = None,
) -> Dict[str, Any]:
    stamp = now or utc_now()
    if color is not None and color != "" and not is_hex_color(color):
        raise ProjectColorInvalid("color must be a #rrggbb hex (color names are no longer accepted), or empty to remove it")

    with transaction(conn):
        current = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if current is None:
            raise ProjectNotFound(str(project_id))
        if color is not None:
            conn.execute(
                "UPDATE projects SET color = ?, updated_at = ? WHERE id = ?",
                (normalize_color(color) if color else None, stamp, project_id),
            )
        if new_name is not None and new_name != current["display_name"]:
            if conn.execute(
                "SELECT 1 FROM projects WHERE display_name = ? AND id != ? AND host_key = 'local'",
                (new_name, project_id),
            ).fetchone():
                raise ProjectNameConflict("name conflict")
            conn.execute(
                "UPDATE projects SET display_name = ?, updated_at = ? WHERE id = ?",
                (new_name, stamp, project_id),
            )
        if description is not None:
            conn.execute(
                "UPDATE projects SET description = ?, updated_at = ? WHERE id = ?",
                (description, stamp, project_id),
            )
        if short_description is not None:
            conn.execute(
                "UPDATE projects SET short_description = ?, updated_at = ? WHERE id = ?",
                (short_description or None, stamp, project_id),
            )
        if default_agent_type is not None:
            conn.execute(
                "UPDATE projects SET default_agent_type = ?, updated_at = ? WHERE id = ?",
                (default_agent_type or None, stamp, project_id),
            )

    logger.info("project_updated_in_db", project_id=project_id)
    resource_push.notify(resource_topics.PROJECTS)
    return dict(
        conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    )


def delete_project(conn: sqlite3.Connection, project_id: int) -> Dict[str, Any]:
    with transaction(conn):
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise ProjectNotFound(str(project_id))
        removed = dict(row)
        conn.execute(
            "UPDATE sessions SET project_id = NULL, project_attribution = 'none' WHERE project_id = ?", (project_id,)
        )
        trust_store.forget_project(conn, project_id)
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        record_tombstone(conn, removed["root"], removed["display_name"])

    logger.info("project_deleted_from_db", project_id=project_id, root=removed["root"])
    resource_push.notify(resource_topics.PROJECTS)
    resource_push.notify(resource_topics.COMPANIES)
    return removed


def touch_project_by_path(
    conn: sqlite3.Connection, working_dir: str, *, now: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    if not table_exists(conn, PROJECTS_TABLE):
        return None
    stamp = now or utc_now()
    root = normalize_root(working_dir)

    with transaction(conn):
        row = conn.execute(
            "SELECT * FROM projects WHERE root = ?", (root,)
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE projects SET last_opened_at = ? WHERE id = ?",
            (stamp, row["id"]),
        )

    return dict(
        conn.execute("SELECT * FROM projects WHERE id = ?", (row["id"],)).fetchone()
    )

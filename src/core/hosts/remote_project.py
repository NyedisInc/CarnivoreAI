
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Callable, Mapping, MutableSet, Optional, Tuple

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


def _ladder(project_uid: Optional[str], root: str, claimed: MutableSet[int],
            find_uid: Callable[[str], Optional[Tuple[int, str]]],
            find_root: Callable[[str], Optional[int]]) -> Tuple[str, Optional[int], Optional[str]]:
    uid = project_uid if isinstance(project_uid, str) and UID_RE.fullmatch(project_uid) else None
    if uid is not None:
        held = find_uid(uid)
        if held is not None:
            return "held", int(held[0]), held[1]
    found = find_root(root)
    if found is None:
        return "mint", None, None
    if uid is not None and int(found) not in claimed:
        return "retag", int(found), root
    return "found", int(found), root


def _first(row: Optional[Tuple[int, ...]]) -> Optional[int]:
    return row[0] if row is not None else None


@dataclass(frozen=True)
class ProjectIndex:

    by_uid: Mapping[str, Tuple[int, str]]
    by_root: Mapping[str, int]


def lookup_remote_project(index: ProjectIndex, host_key: str, far_dir: str, *, root: str,
                          project_uid: Optional[str], claimed: MutableSet[int]) -> Optional[ProjectBinding]:
    kind, pid, found_root = _ladder(project_uid, root, claimed, index.by_uid.get,
                                    lambda r: index.by_root.get(r))
    if kind in ("retag", "mint"):
        return None
    if kind == "held":
        claimed.add(pid)
    return ProjectBinding(project_id=pid, attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST, rule=BINDING_MATCHED, root=found_root)


def bind_remote_project(conn: sqlite3.Connection, host_key: str, far_dir: str, *,
                        now: Optional[str] = None, root: Optional[str] = None,
                        project_uid: Optional[str] = None, claimed: Optional[MutableSet[int]] = None) -> ProjectBinding:
    root = root or remote_project_root(host_key, far_dir)
    stamp = now or utc_now()
    claimed = claimed if claimed is not None else set()
    uid = project_uid if isinstance(project_uid, str) and UID_RE.fullmatch(project_uid) else None
    try:
        kind, pid, found_root = _ladder(
            project_uid, root, claimed,
            lambda u: conn.execute("SELECT id, root FROM projects WHERE uid = ?", (u,)).fetchone(),
            lambda r: _first(conn.execute("SELECT id FROM projects WHERE root = ? AND host_key = ?", (r, host_key)).fetchone()))
        if kind == "held":
            claimed.add(pid)
        if kind == "retag":
            conn.execute("UPDATE projects SET uid = ? WHERE id = ?", (uid, pid))
            claimed.add(pid)
        if kind != "mint":
            return ProjectBinding(project_id=pid, attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST,
                                  rule=BINDING_MATCHED, root=found_root)
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

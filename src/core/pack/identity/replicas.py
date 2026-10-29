
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional

import structlog

from src.core.db import transaction
from src.core.mcp import family_signals
from src.core.pack.identity import home
from src.core.pack.identity.ddl import TRANSPORT_RUNGS
from src.core.pack.trust_carry import store as trust_store
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

UID_IS_HOME = "project_uid_is_home"
NAME_TAKEN = "project_name_taken"
ROOT_IN_USE = "project_root_in_use"
NOT_REPLICA_OF_CALLER = "not_replica_of_caller"


class ReplicaRefused(Exception):

    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def list_replicas(conn: sqlite3.Connection, project_uid: str) -> List[Dict[str, Any]]:
    rows = [dict(r) for r in conn.execute(
        "SELECT install_id, root, transport_rung, state, created_at, updated_at FROM project_replicas "
        "WHERE project_uid = ? ORDER BY created_at, install_id", (project_uid,)).fetchall()]
    for row in rows:
        row["label"] = home.machine_label(conn, row["install_id"])
    return rows


def record_replica(conn: sqlite3.Connection, project_uid: str, install_id: str, root: Optional[str], transport: str) -> None:
    if transport not in TRANSPORT_RUNGS:
        raise ValueError(f"unknown transport rung {transport!r}")
    stamp = utc_now()
    with transaction(conn):
        conn.execute(
            "INSERT INTO project_replicas (project_uid, install_id, root, transport_rung, state, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?) ON CONFLICT(project_uid, install_id) DO UPDATE SET "
            "root = excluded.root, transport_rung = excluded.transport_rung, state = 'active', updated_at = excluded.updated_at",
            (project_uid, install_id, root, transport, stamp, stamp))
    family_signals.invalidate("pack")


def forget_replica(conn: sqlite3.Connection, project_uid: str, install_id: str) -> bool:
    with transaction(conn):
        cur = conn.execute("DELETE FROM project_replicas WHERE project_uid = ? AND install_id = ?", (project_uid, install_id))
    family_signals.invalidate("pack")
    return cur.rowcount == 1


def _default_root(name: str, uid: str) -> str:
    from src.config import settings

    folder = re.sub(r"[^\w .-]", "_", name).strip(" .") or uid[:12]
    return os.path.join(str(settings.get_working_dir()), folder)


def _ensure_company(conn: sqlite3.Connection, uid: Optional[str], name: Optional[str]) -> Optional[int]:
    if not uid or not name:
        return None
    found = conn.execute("SELECT id FROM companies WHERE uid = ?", (uid,)).fetchone()
    if found is None:
        found = conn.execute("SELECT id FROM companies WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        if found is not None:
            conn.execute("UPDATE companies SET uid = ?, updated_at = ? WHERE id = ?", (uid, utc_now(), found[0]))
    if found is None:
        stamp = utc_now()
        cur = conn.execute("INSERT INTO companies (name, uid, created_at, updated_at) VALUES (?, ?, ?, ?)", (name, uid, stamp, stamp))
        return int(cur.lastrowid)
    return int(found[0])


def accept_replica(conn: sqlite3.Connection, *, home_install_id: str, project_uid: str, name: str, root: Optional[str],
                   company_uid: Optional[str] = None, company_name: Optional[str] = None, source_trusted: bool = False,
                   source_imports_ok: bool = False) -> Dict[str, Any]:
    from src.core.project_store import normalize_root
    from src.core.project_writes import ProjectNameConflict, ProjectRootRefused, create_project

    existing = conn.execute("SELECT * FROM projects WHERE uid = ?", (project_uid,)).fetchone()
    if existing is not None:
        if existing["pack_state"] == home.REPLICA and existing["home_install_id"] == home_install_id:
            return _answer(existing, created=False)
        raise ReplicaRefused(UID_IS_HOME, f"this machine already holds project {project_uid} and it is not a replica of that machine")
    created = False
    target = normalize_root(root) if root else None
    row = conn.execute("SELECT * FROM projects WHERE root = ?", (target,)).fetchone() if target else None
    if row is not None and row["pack_state"] != home.HOME:
        raise ReplicaRefused(ROOT_IN_USE, f"the folder {target} already belongs to a project that is not a plain one here")
    if row is None:
        target = target or _default_root(name, project_uid)
        existed = os.path.exists(target)
        os.makedirs(target, exist_ok=True)
        try:
            row = create_project(conn, name=name, path=target)
        except ProjectNameConflict as exc:
            raise ReplicaRefused(NAME_TAKEN, str(exc)) from exc
        except ProjectRootRefused as exc:
            raise ReplicaRefused(ProjectRootRefused.CODE, str(exc)) from exc
        created = True
        if source_trusted and not existed:
            from src.config import settings

            trust_store.record(conn, target, project_uid, home_install_id, f"replica:{project_uid}", projects_dir=str(settings.get_working_dir()), imports_ok=source_imports_ok)
    company_id = _ensure_company(conn, company_uid, company_name)
    with transaction(conn):
        conn.execute(
            "UPDATE projects SET uid = ?, pack_state = 'replica', home_install_id = ?, moved_to_install_id = NULL, "
            "company_id = COALESCE(company_id, ?), updated_at = ? WHERE id = ?",
            (project_uid, home_install_id, company_id, utc_now(), row["id"]))
    home.notify_changed()
    logger.info("project_replica_registered", project_uid=project_uid, home=home_install_id, created=created)
    return _answer(conn.execute("SELECT * FROM projects WHERE uid = ?", (project_uid,)).fetchone(), created=created)


def _answer(row: sqlite3.Row, *, created: bool) -> Dict[str, Any]:
    return {"project_uid": row["uid"], "project_id": row["id"], "name": row["display_name"], "root": row["root"],
            "state": row["pack_state"], "created": created}


def detach_replica(conn: sqlite3.Connection, *, home_install_id: str, project_uid: str) -> bool:
    from src.core.pack.identity.uid import new_uid

    row = conn.execute("SELECT id, pack_state, home_install_id FROM projects WHERE uid = ?", (project_uid,)).fetchone()
    if row is None:
        return False
    if row["pack_state"] != home.REPLICA or row["home_install_id"] != home_install_id:
        raise ReplicaRefused(NOT_REPLICA_OF_CALLER, "that project is not a replica of the calling machine")
    with transaction(conn):
        trust_store.forget_project(conn, row["id"])
        conn.execute("UPDATE projects SET uid = ?, pack_state = 'home', home_install_id = NULL, updated_at = ? WHERE id = ?",
                     (new_uid(), utc_now(), row["id"]))
    home.notify_changed()
    logger.info("project_replica_detached", project_uid=project_uid, home=home_install_id)
    return True


from __future__ import annotations

import os
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

import structlog

from src.core.db import transaction
from src.core.hosts.ddl import LOCAL_HOST_KEY
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
        conn.execute("DELETE FROM pack_bundle_tips WHERE project_uid = ? AND install_id = ?", (project_uid, install_id))
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
                   source_imports_ok: bool = False, member_caller: bool = False) -> Dict[str, Any]:
    from src.core.project_store import normalize_root
    from src.core.project_writes import ProjectNameConflict, ProjectRootConflict, ProjectRootRefused, create_project

    if member_caller and not _callers_copy(conn, project_uid, home_install_id):
        _require_member_root(root or _default_root(name, project_uid), conn)
    existing = conn.execute("SELECT * FROM projects WHERE uid = ?", (project_uid,)).fetchone()
    if existing is not None and existing["host_key"] != LOCAL_HOST_KEY:
        with transaction(conn):
            conn.execute("UPDATE projects SET uid = ? WHERE id = ?", (uuid.uuid4().hex, existing["id"]))
        existing = None
    if existing is not None:
        if existing["pack_state"] == home.REPLICA and existing["home_install_id"] == home_install_id:
            return _answer(existing, created=False, folder_made=False)
        raise ReplicaRefused(UID_IS_HOME, f"this machine already holds project {project_uid} and it is not a replica of that machine")
    created = False
    folder_made = False
    target = normalize_root(root) if root else None
    row = conn.execute("SELECT * FROM projects WHERE root = ?", (target,)).fetchone() if target else None
    revived = False
    if row is not None and row["archived_at"] and row["pack_state"] == home.HOME:
        target, revived = row["root"], True
    if row is None and not root:
        default = _default_root(name, project_uid)
        old = conn.execute("SELECT * FROM projects WHERE root = ?", (default,)).fetchone()
        if old is not None and old["archived_at"] and old["pack_state"] == home.HOME:
            row, target, revived = old, default, True
    if row is not None and row["pack_state"] != home.HOME:
        raise ReplicaRefused(ROOT_IN_USE, f"the folder {target} already belongs to a project that is not a plain one here")
    if member_caller and row is not None and not _member_may_take(row, revived, home_install_id):
        raise ReplicaRefused(ROOT_IN_USE, f"the folder {target} already belongs to a project here")
    adopted = row is not None and not revived
    if revived:
        existed = os.path.lexists(target)
        os.makedirs(target, exist_ok=True)
        folder_made = not existed
    if row is None:
        target = target or _default_root(name, project_uid)
        existed = os.path.lexists(target)
        os.makedirs(target, exist_ok=True)
        try:
            row = create_project(conn, name=name, path=target)
        except ProjectNameConflict as exc:
            raise ReplicaRefused(NAME_TAKEN, str(exc)) from exc
        except ProjectRootRefused as exc:
            raise ReplicaRefused(ProjectRootRefused.CODE, str(exc)) from exc
        except ProjectRootConflict as exc:
            if not member_caller:
                raise
            raise ReplicaRefused(ROOT_IN_USE, "that folder already belongs to a project here") from exc
        created = True
        folder_made = not existed
        if source_trusted and not existed:
            from src.config import settings

            trust_store.record(conn, target, project_uid, home_install_id, f"replica:{project_uid}", projects_dir=str(settings.get_working_dir()), imports_ok=source_imports_ok)
    company_id = _ensure_company(conn, company_uid, company_name)
    with transaction(conn):
        conn.execute(
            "UPDATE projects SET uid = ?, pack_state = 'replica', home_install_id = ?, moved_to_install_id = NULL, "
            "company_id = COALESCE(company_id, ?), archived_at = NULL, updated_at = ? WHERE id = ?",
            (project_uid, home_install_id, company_id, utc_now(), row["id"]))
    home.notify_changed()
    logger.info("project_replica_registered", project_uid=project_uid, home=home_install_id, created=created)
    answer = _answer(conn.execute("SELECT * FROM projects WHERE uid = ?", (project_uid,)).fetchone(), created=created, folder_made=folder_made)
    answer.update(adopted=adopted, revived=revived)
    return answer


def _callers_copy(conn: sqlite3.Connection, project_uid: str, home_install_id: str) -> bool:
    return conn.execute("SELECT 1 FROM projects WHERE uid = ? AND host_key = ? AND pack_state = ? AND home_install_id = ?",
                        (project_uid, LOCAL_HOST_KEY, home.REPLICA, home_install_id)).fetchone() is not None


def _require_member_root(root: str, conn: sqlite3.Connection) -> None:
    from src.core.pack.transport import bundles
    from src.core.project_store import normalize_root
    from src.core.project_writes import _base_folders, find_root_clash
    from src.core.session_project_binding import fold_path, swallows_live_root
    from src.core.transcript_import_paths import canonical

    target = normalize_root(root)
    real = canonical(target) or target
    inside_base = False
    for base in _base_folders():
        base_real = os.path.realpath(base)
        if real != base_real and os.path.commonpath([real, base_real]) == base_real:
            inside_base = True
            break
    if not inside_base:
        raise ReplicaRefused("member_root_refused", "that folder is outside this computer's projects folders", 403)
    if conn.execute("SELECT 1 FROM projects WHERE root = ? AND host_key = ?", (target, LOCAL_HOST_KEY)).fetchone() is not None:
        return
    if find_root_clash(conn, target) is not None:
        raise ReplicaRefused(ROOT_IN_USE, "that folder already belongs to a project here")
    if any(part in (".", "..") for part in target.split(os.sep)):
        raise ReplicaRefused("member_root_refused", "that folder path has . or .. parts", 403)
    stored = [canonical(r[0]) or r[0] for r in conn.execute("SELECT root FROM projects WHERE root IS NOT NULL AND root != '' AND host_key = ?", (LOCAL_HOST_KEY,))]
    folded = fold_path(real)
    if any(folded.startswith(fold_path(s) + "/") for s in stored):
        raise ReplicaRefused("member_root_refused", "that folder is inside a project that already lives here", 403)
    if swallows_live_root(real, {s: 0 for s in stored}):
        raise ReplicaRefused("member_root_refused", "that folder holds another project's folder", 403)
    if os.path.lexists(target) or os.path.lexists(real):
        try:
            empty = os.path.isdir(real) and not os.listdir(real)
        except OSError:
            empty = False
        if not empty:
            raise ReplicaRefused("member_root_refused", "that folder is not an empty folder", 403)
    if bundles.inside_other_repo(real):
        raise ReplicaRefused("member_root_refused", "that folder is inside another git repository", 403)


def _member_may_take(row: sqlite3.Row, revived: bool, home_install_id: str) -> bool:
    if not revived:
        return False
    from pathlib import Path

    from src.config import settings
    from src.core.pack.jobs.store import JobStore

    record = JobStore(Path(settings.get_state_dir())).made_copy_get(os.path.realpath(row["root"]))
    return bool(record) and record.get("home_install_id") == home_install_id


def _answer(row: sqlite3.Row, *, created: bool, folder_made: bool) -> Dict[str, Any]:
    return {"project_uid": row["uid"], "project_id": row["id"], "name": row["display_name"], "root": row["root"],
            "state": row["pack_state"], "created": created, "folder_made": folder_made}


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


from __future__ import annotations

import asyncio
import os
import sqlite3
from contextlib import closing
from typing import Any, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.core.db import DatastoreUnreadableError, connect, db_path_for, table_exists, transaction
from src.core.hosts.ddl import host_scope
from src.core.mcp import family_signals
from src.core.pack.identity.ddl import PACK_STATES
from src.core.pack.trust_carry import store as trust_store
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

HOME, REPLICA, MOVED_AWAY = PACK_STATES
MOVED_AWAY_CODE = "project_moved_away"


class ProjectMovedAway(HTTPException):

    def __init__(self, project: str, moved_to: Optional[str], root: str) -> None:
        where = moved_to or "another machine"
        super().__init__(status_code=409, detail={
            "code": MOVED_AWAY_CODE, "project": project, "moved_to": moved_to, "root": root,
            "detail": f"the project {project!r} moved to {where}; nothing can start here until it is moved back"})


def _has_state(conn: sqlite3.Connection) -> bool:
    return table_exists(conn, "projects") and any(r[1] == "pack_state" for r in conn.execute("PRAGMA table_info(projects)"))


def machine_label(conn: sqlite3.Connection, install_id: Optional[str]) -> Optional[str]:
    if not install_id:
        return None
    if table_exists(conn, "hosts") and any(r[1] == "peer_install_id" for r in conn.execute("PRAGMA table_info(hosts)")):
        row = conn.execute("SELECT label FROM hosts WHERE peer_install_id = ?", (install_id,)).fetchone()
        if row and row[0]:
            return str(row[0])
    return install_id


def attach_machine_labels(conn: sqlite3.Connection, rows: List[Dict[str, Any]]) -> None:
    for row in rows:
        row["moved_to_label"] = machine_label(conn, row.get("moved_to_install_id"))
        row["home_label"] = machine_label(conn, row.get("home_install_id"))


def _spellings(path: str) -> set:
    expanded = os.path.expanduser(path)
    return {expanded.rstrip("/") or "/", os.path.realpath(expanded).rstrip("/") or "/"}


def _inside(target: set, root: set) -> bool:
    return any(t == r or t.startswith(r + "/") for t in target for r in root)


def moved_away_for(conn: sqlite3.Connection, working_dir: str) -> Optional[Dict[str, Any]]:
    """The moved-away project whose folder holds ``working_dir``, None when none does.

    Description: the MOST SPECIFIC project holding the folder decides, so a live project that sits inside a moved-away
      project's folder is not locked by it. Cheap in the common case: one indexless query that finds no moved-away row.
    Inputs: conn; working_dir (str). Output: the project row dict (with ``moved_to_label``) | None.
    Example: moved_away_for(conn, "/p/ledgerbot/sub")  # {"display_name": "ledgerbot", ...}
    """
    if not working_dir or not _has_state(conn):
        return None
    moved = [dict(r) for r in conn.execute("SELECT * FROM projects WHERE pack_state = 'moved_away'").fetchall()]
    if not moved:
        return None
    target = _spellings(working_dir)
    holding = [m for m in moved if _inside(target, _spellings(m["root"]))]
    if not holding:
        return None
    best = max(holding, key=lambda m: len(m["root"]))
    for other in conn.execute("SELECT root FROM projects WHERE pack_state != 'moved_away'").fetchall():
        if len(other[0]) > len(best["root"]) and _inside(target, _spellings(other[0])):
            return None
    best["moved_to_label"] = machine_label(conn, best.get("moved_to_install_id"))
    return best


def refuse_if_moved_away(working_dir: Optional[str]) -> None:
    if not working_dir:
        return
    from src.config import settings

    try:
        with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
            found = moved_away_for(conn, working_dir)
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("moved_away_check_unreadable", working_dir=working_dir, error_type=type(exc).__name__)
        return
    if found is not None:
        logger.info("project_moved_away_refused", project=found["display_name"], working_dir=working_dir)
        raise ProjectMovedAway(found["display_name"], found.get("moved_to_label"), found["root"])


async def require_active(working_dir: Optional[str]) -> None:
    await asyncio.to_thread(refuse_if_moved_away, working_dir)


def _working_dir_of_tmux(socket_name: str, name: str) -> Optional[str]:
    from src.config import settings

    try:
        with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
            scope_sql, scope_params = host_scope(conn)
            row = conn.execute("SELECT working_dir FROM sessions WHERE tmux_name = ? AND tmux_socket = ?" + scope_sql
                               + " ORDER BY id DESC LIMIT 1", (name, socket_name, *scope_params)).fetchone()
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("moved_away_check_unreadable", tmux_name=name, error_type=type(exc).__name__)
        return None
    return row[0] if row else None


async def require_active_tmux(socket_name: str, name: str) -> None:
    await require_active(await asyncio.to_thread(_working_dir_of_tmux, socket_name, name))


def notify_changed() -> None:
    from src.core.resource_push import notify, topics

    notify(topics.PROJECTS)
    notify(topics.COMPANIES)


def set_state(conn: sqlite3.Connection, project_id: int, state: str, *, home_install_id: Optional[str] = None,
              moved_to_install_id: Optional[str] = None) -> Dict[str, Any]:
    if state not in PACK_STATES:
        raise ValueError(f"unknown pack state {state!r}")
    if state == MOVED_AWAY and not moved_to_install_id:
        raise ValueError("a moved-away project must name the machine it moved to")
    if state == REPLICA and not home_install_id:
        raise ValueError("a replica must name its home machine")
    with transaction(conn):
        cur = conn.execute(
            "UPDATE projects SET pack_state = ?, home_install_id = ?, moved_to_install_id = ?, updated_at = ? WHERE id = ?",
            (state, home_install_id if state == REPLICA else None, moved_to_install_id if state == MOVED_AWAY else None,
             utc_now(), project_id))
        if cur.rowcount != 1:
            raise ValueError(f"no project {project_id}")
        if state == MOVED_AWAY:
            trust_store.forget_project(conn, project_id)
    family_signals.invalidate("pack")
    notify_changed()
    return dict(conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())


from __future__ import annotations

import posixpath
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Mapping, Optional, Sequence

import structlog

from src.core.db import transaction
from src.core.db_models import SESSION_ATTRIBUTION_DERIVED_DEEPEST, SESSION_LIFECYCLE_RUNNING, SESSION_LIFECYCLE_STOPPED
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.hosts.identity import PEER_ROOT_SCHEME
from src.core.hosts.remote_project import bind_remote_project
from src.core.session_project_binding import BINDING_MATCHED, ProjectBinding
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

FEDERATION_NS = uuid.UUID("3f1c5a52-6d0e-5b7a-9a41-1630c0ffee01")
PEER_ORIGIN = "peer"
PEER_SOCKET = "peer"
MAX_ROWS = 500
MAX_NAME, MAX_LABEL, MAX_DIR = 128, 256, 1024
PRUNE_GRACE_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class Shadow:

    session_id: int
    project_id: Optional[int]
    project_name: Optional[str]


def shadow_uuid(peer_install_id: str, peer_session_uuid: str) -> str:
    return str(uuid.uuid5(FEDERATION_NS, f"{peer_install_id}:{peer_session_uuid}"))


def peer_project_root(host_key: str, far_path: str) -> str:
    return f"{PEER_ROOT_SCHEME}{host_key}{far_path}"


def usable(row: Mapping[str, object]) -> bool:
    name, peer_uuid, wd, label = row.get("name"), row.get("session_uuid"), row.get("working_dir"), row.get("label")
    return (isinstance(name, str) and 0 < len(name) <= MAX_NAME and ":" not in name
            and isinstance(peer_uuid, str) and 0 < len(peer_uuid) <= MAX_NAME
            and isinstance(wd, str) and len(wd) <= MAX_DIR and posixpath.isabs(wd) and posixpath.normpath(wd) == wd
            and (label is None or (isinstance(label, str) and len(label) <= MAX_LABEL)))


def _moved_home_project(conn: sqlite3.Connection, peer_uuid: str) -> Optional[int]:
    found = conn.execute("SELECT project_id FROM sessions WHERE session_uuid = ? AND host_key = ? AND origin != ? "
                         "AND project_id IS NOT NULL ORDER BY id DESC LIMIT 1",
                         (peer_uuid, LOCAL_HOST_KEY, PEER_ORIGIN)).fetchone()
    return int(found[0]) if found is not None else None


def _project(conn: sqlite3.Connection, host_key: str, far_dir: str, now: str, peer_uuid: str):
    home = _moved_home_project(conn, peer_uuid)
    if home is not None:
        binding = ProjectBinding(project_id=home, attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST, rule=BINDING_MATCHED)
    else:
        binding = bind_remote_project(conn, host_key, far_dir, now=now, root=peer_project_root(host_key, far_dir))
    name = None
    if binding.project_id is not None:
        found = conn.execute("SELECT display_name FROM projects WHERE id = ?", (binding.project_id,)).fetchone()
        name = found[0] if found else None
    return binding, name


def _existing(conn: sqlite3.Connection, host_key: str, peer_uuid: str, local_uuid: str) -> Optional[int]:
    row = conn.execute("SELECT session_id FROM peer_sessions WHERE host_key = ? AND peer_session_uuid = ?",
                       (host_key, peer_uuid)).fetchone()
    if row is not None:
        return int(row[0])
    orphan = conn.execute("SELECT id FROM sessions WHERE session_uuid = ? AND origin = ? AND host_key = ?",
                          (local_uuid, PEER_ORIGIN, host_key)).fetchone()
    return int(orphan[0]) if orphan is not None else None


def sync_peer(conn: sqlite3.Connection, *, host_key: str, peer_install_id: str,
              rows: Sequence[Mapping[str, object]], complete: bool) -> Dict[str, Shadow]:
    now, out, seen, skipped = utc_now(), {}, [], 0
    with transaction(conn):
        for row in rows:
            if not usable(row):
                skipped += 1
                logger.info("peer_shadow_row_skipped", host=host_key, reason="unusable name, uuid, folder or label")
                continue
            name, peer_uuid = str(row["name"]), str(row["session_uuid"])
            local_uuid = shadow_uuid(peer_install_id, peer_uuid)
            binding, project_name = _project(conn, host_key, str(row["working_dir"]), now, peer_uuid)
            wanted = (binding.project_id, binding.attribution, row["working_dir"], name, row.get("agent_type"),
                      row.get("agent_family"), row.get("agent_family_source") or "unknown", row.get("label"))
            sid = _existing(conn, host_key, peer_uuid, local_uuid)
            if sid is None:
                sid = conn.execute(
                    "INSERT INTO sessions (session_uuid, project_id, project_attribution, working_dir, tmux_socket, "
                    "tmux_name, origin, agent_type, agent_family, agent_family_source, title, lifecycle, "
                    "last_seen_running_at, host_key, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)",
                    (local_uuid, wanted[0], wanted[1], wanted[2], PEER_SOCKET, name, PEER_ORIGIN, *wanted[4:], now,
                     host_key, now, now)).lastrowid
            elif conn.execute(
                    "SELECT 1 FROM sessions WHERE id = ? AND lifecycle = ? AND project_id IS ? AND project_attribution IS ? "
                    "AND working_dir IS ? AND tmux_name IS ? AND agent_type IS ? AND agent_family IS ? "
                    "AND agent_family_source IS ? AND title IS ?", (sid, SESSION_LIFECYCLE_RUNNING, *wanted)).fetchone() is None:
                conn.execute(
                    "UPDATE sessions SET project_id = ?, project_attribution = ?, working_dir = ?, tmux_name = ?, "
                    "agent_type = ?, agent_family = ?, agent_family_source = ?, title = ?, lifecycle = ?, "
                    "last_seen_running_at = ?, updated_at = ? WHERE id = ? AND origin = ? AND host_key = ?",
                    (*wanted, SESSION_LIFECYCLE_RUNNING, now, now, sid, PEER_ORIGIN, host_key))
            if conn.execute("SELECT 1 FROM peer_sessions WHERE host_key = ? AND peer_session_uuid = ? AND peer_row_id IS ? "
                            "AND peer_name = ? AND session_id = ?",
                            (host_key, peer_uuid, row.get("row_id"), name, sid)).fetchone() is None:
                conn.execute(
                    "INSERT INTO peer_sessions (host_key, peer_session_uuid, peer_row_id, peer_name, session_id) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(host_key, peer_session_uuid) DO UPDATE SET "
                    "peer_row_id = excluded.peer_row_id, peer_name = excluded.peer_name",
                    (host_key, peer_uuid, row.get("row_id"), name, sid))
            seen.append(sid)
            out[name] = Shadow(sid, binding.project_id, project_name)
        if complete and not skipped:  # could not be read
            _prune(conn, host_key)
            marks = ",".join("?" * len(seen))
            conn.execute(
                f"UPDATE sessions SET lifecycle = ?, updated_at = ? WHERE origin = ? AND host_key = ? "
                f"AND lifecycle = ? AND id NOT IN ({marks})",
                (SESSION_LIFECYCLE_STOPPED, now, PEER_ORIGIN, host_key, SESSION_LIFECYCLE_RUNNING, *seen))
    return out


def _prune(conn: sqlite3.Connection, host_key: str) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=PRUNE_GRACE_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for (sid,) in conn.execute("SELECT id FROM sessions WHERE origin = ? AND host_key = ? AND lifecycle = ? "
                               "AND updated_at < ?", (PEER_ORIGIN, host_key, SESSION_LIFECYCLE_STOPPED, cutoff)).fetchall():
        _try_delete(conn, "DELETE FROM sessions WHERE id = ?", (sid,))
    _drop_projects(conn, host_key)


def _try_delete(conn: sqlite3.Connection, sql: str, args: tuple) -> None:
    try:
        conn.execute(sql, args)
    except sqlite3.IntegrityError as exc:
        logger.info("peer_shadow_delete_kept", reason=str(exc)[:80])


def _drop_projects(conn: sqlite3.Connection, host_key: str) -> None:
    for (pid,) in conn.execute(
            "SELECT id FROM projects WHERE host_key = ? AND root LIKE ? AND id NOT IN "
            "(SELECT project_id FROM sessions WHERE project_id IS NOT NULL)",
            (host_key, f"{PEER_ROOT_SCHEME}%")).fetchall():
        _try_delete(conn, "DELETE FROM projects WHERE id = ?", (pid,))


def remove_peer(conn: sqlite3.Connection, host_key: str) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM peer_sessions WHERE host_key = ?", (host_key,))
        conn.execute("UPDATE sessions SET lifecycle = ? WHERE origin = ? AND host_key = ? AND lifecycle = ?",
                     (SESSION_LIFECYCLE_STOPPED, PEER_ORIGIN, host_key, SESSION_LIFECYCLE_RUNNING))
        for (sid,) in conn.execute("SELECT id FROM sessions WHERE origin = ? AND host_key = ?",
                                   (PEER_ORIGIN, host_key)).fetchall():
            _try_delete(conn, "DELETE FROM sessions WHERE id = ?", (sid,))
        _drop_projects(conn, host_key)

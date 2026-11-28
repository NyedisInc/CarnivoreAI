
from __future__ import annotations

import posixpath
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Mapping, Optional, Sequence, Tuple

import structlog

from src.core import resource_push
from src.core.db import transaction
from src.core.db_models import SESSION_ATTRIBUTION_DERIVED_DEEPEST, SESSION_LIFECYCLE_RUNNING, SESSION_LIFECYCLE_STOPPED
from src.core.pack.machines import capabilities
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope
from src.core.hosts.identity import PEER_ROOT_SCHEME
from src.core.hosts.remote_project import UID_RE, bind_remote_project
from src.core.project_lineage.peer_parents import sync_peer_project_parents
from src.core.project_tombstones import tombstoned_roots
from src.core.resource_push import topics as resource_topics
from src.core.session_sleep import SLEEP_SOURCES
from src.core.session_project_binding import BINDING_MATCHED, ProjectBinding
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

FEDERATION_NS = uuid.UUID("3f1c5a52-6d0e-5b7a-9a41-1630c0ffee01")
PEER_ORIGIN = "peer"
PEER_SOCKET = "peer"
MAX_ROWS = 500
MAX_NAME, MAX_LABEL, MAX_DIR, MAX_STAMP = 128, 256, 1024, 64
MAX_EPOCH = 10**12
PRUNE_GRACE_SECONDS = 7 * 24 * 3600


def clean_stamp(value: object) -> Optional[str]:
    return value if isinstance(value, str) and 0 < len(value) <= MAX_STAMP else None


def clean_epoch(value: object) -> Optional[int]:
    return value if type(value) is int and 0 < value <= MAX_EPOCH else None


@dataclass(frozen=True)
class Shadow:

    session_id: int
    project_id: Optional[int]
    project_name: Optional[str]


def shadow_uuid(peer_install_id: str, peer_session_uuid: str) -> str:
    return str(uuid.uuid5(FEDERATION_NS, f"{peer_install_id}:{peer_session_uuid}"))


def peer_project_root(host_key: str, far_path: str) -> str:
    return f"{PEER_ROOT_SCHEME}{host_key}{far_path}"


JOB_WORKER_DIR = re.compile(r"/\.carnivore/jobs/folders/[^/]+/slot[0-9]+(?:/|$)")


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


def _project(conn: sqlite3.Connection, host_key: str, far_dir: str, now: str, peer_uuid: str,
             project_uid: Optional[str] = None, claimed: Optional[set] = None):
    home = _moved_home_project(conn, peer_uuid)
    if home is not None:
        binding = ProjectBinding(project_id=home, attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST, rule=BINDING_MATCHED)
    else:
        binding = bind_remote_project(conn, host_key, far_dir, now=now, root=peer_project_root(host_key, far_dir),
                                      project_uid=project_uid, claimed=claimed)
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
              rows: Sequence[Mapping[str, object]], complete: bool,
              asleep: Optional[Sequence[Mapping[str, object]]] = None) -> Dict[str, Shadow]:
    if capabilities.mesh_on():
        from src.core.federation import shadow_rows_diff
        return shadow_rows_diff.sync_peer_diff(conn, host_key=host_key, peer_install_id=peer_install_id, rows=rows,
                                               complete=complete, asleep=asleep)
    return full_sync(conn, host_key=host_key, peer_install_id=peer_install_id, rows=rows, complete=complete, asleep=asleep)


def _tombstoned_peer_row(conn: sqlite3.Connection, host_key: str, far_dir: str, peer_uuid: str,
                         project_uid: Optional[str], tombstones: set[str]) -> bool:
    root = peer_project_root(host_key, far_dir)
    if root not in tombstones:
        return False
    if _moved_home_project(conn, peer_uuid) is not None:
        return False
    if isinstance(project_uid, str) and UID_RE.fullmatch(project_uid):
        if conn.execute("SELECT 1 FROM projects WHERE uid = ?", (project_uid,)).fetchone() is not None:
            return False
    if conn.execute("SELECT 1 FROM projects WHERE root = ? AND host_key = ?", (root, host_key)).fetchone() is not None:
        return False
    return True


def full_sync(conn: sqlite3.Connection, *, host_key: str, peer_install_id: str,
              rows: Sequence[Mapping[str, object]], complete: bool,
              asleep: Optional[Sequence[Mapping[str, object]]] = None) -> Dict[str, Shadow]:
    now, out, seen, skipped, rested, claimed, minted = utc_now(), {}, [], 0, [], set(), False
    parent_updates: Dict[str, Optional[str]] = {}
    live = {str(r.get("session_uuid")) for r in rows}
    todo = [(r, None) for r in rows] + [(r, r.get("source")) for r in (asleep or ()) if str(r.get("session_uuid")) not in live
                                         and r.get("source") in SLEEP_SOURCES]
    with transaction(conn):
        tombstones = tombstoned_roots(conn)
        for row, sleep_source in todo:
            lifecycle = SESSION_LIFECYCLE_STOPPED if sleep_source else SESSION_LIFECYCLE_RUNNING
            if not usable(row):
                skipped += 1
                logger.info("peer_shadow_row_skipped", host=host_key, reason="unusable name, uuid, folder or label")
                continue
            name, peer_uuid = str(row["name"]), str(row["session_uuid"])
            puid = row.get("project_uid") if isinstance(row.get("project_uid"), str) else None
            if _tombstoned_peer_row(conn, host_key, str(row["working_dir"]), peer_uuid, puid, tombstones):
                continue
            local_uuid = shadow_uuid(peer_install_id, peer_uuid)
            binding, project_name = _project(conn, host_key, str(row["working_dir"]), now, peer_uuid, puid, claimed)
            if binding.created_project:
                minted = True
            if puid is not None and UID_RE.fullmatch(puid) and "parent_project_uid" in row:
                raw_parent = row.get("parent_project_uid")
                parent_updates[puid] = raw_parent if isinstance(raw_parent, str) and UID_RE.fullmatch(raw_parent) else None
            wanted = (
                binding.project_id, binding.attribution, row["working_dir"], name, row.get("agent_type"),
                row.get("agent_family"), row.get("agent_family_source") or "unknown", row.get("label"),
                clean_stamp(row.get("last_work_at")), clean_epoch(row.get("tmux_created_epoch")),
            )
            sid = _existing(conn, host_key, peer_uuid, local_uuid)
            sid = _upsert_row(conn, host_key=host_key, sid=sid, row=row, name=name, local_uuid=local_uuid, wanted=wanted,
                              lifecycle=lifecycle, sleep_source=sleep_source, now=now)
            if sleep_source:
                rested.append(sid)
                continue
            seen.append(sid)
            out[name] = Shadow(sid, binding.project_id, project_name)
        if parent_updates and sync_peer_project_parents(conn, parent_updates):
            minted = True
        _finish(conn, host_key=host_key, asleep=asleep, skipped=skipped, complete=complete, rested=rested, seen=seen, now=now)
    if minted:
        resource_push.notify(resource_topics.PROJECTS)
    return out


def _epoch_taken(conn: sqlite3.Connection, *, host_key: str, name: str, epoch: int,
                 ignore_sid: Optional[int]) -> bool:
    host_sql, host_params = host_scope(conn, host_key)
    return conn.execute(
        f"SELECT 1 FROM sessions WHERE tmux_socket = ? AND tmux_name = ? "
        f"AND tmux_created_epoch = ?{host_sql} AND (? IS NULL OR id != ?) LIMIT 1",
        (PEER_SOCKET, name, epoch, *host_params, ignore_sid, ignore_sid),
    ).fetchone() is not None


def _upsert_row(conn: sqlite3.Connection, *, host_key: str, sid: Optional[int], row: Mapping[str, object], name: str,
                local_uuid: str, wanted: tuple, lifecycle: str, sleep_source: Optional[str], now: str) -> int:
    peer_uuid = str(row["session_uuid"])
    if wanted[9] is not None and _epoch_taken(conn, host_key=host_key, name=name, epoch=wanted[9], ignore_sid=sid):
        wanted = (*wanted[:9], None)
    if sid is None:
        sid = conn.execute(
            "INSERT INTO sessions (session_uuid, project_id, project_attribution, working_dir, tmux_socket, "
            "tmux_name, tmux_created_epoch, origin, agent_type, agent_family, agent_family_source, title, "
            "last_work_at, lifecycle, lifecycle_source, last_seen_running_at, host_key, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (local_uuid, wanted[0], wanted[1], wanted[2], PEER_SOCKET, name, wanted[9], PEER_ORIGIN,
             wanted[4], wanted[5], wanted[6], wanted[7], wanted[8], lifecycle,
             sleep_source, now, host_key, now, now)).lastrowid
    elif conn.execute(
            "SELECT 1 FROM sessions WHERE id = ? AND lifecycle = ? AND lifecycle_source IS ? AND project_id IS ? "
            "AND project_attribution IS ? AND working_dir IS ? AND tmux_name IS ? AND agent_type IS ? "
            "AND agent_family IS ? AND agent_family_source IS ? AND title IS ? AND last_work_at IS ? "
            "AND tmux_created_epoch IS ?",
            (sid, lifecycle, sleep_source, *wanted)).fetchone() is None:
        conn.execute(
            "UPDATE sessions SET project_id = ?, project_attribution = ?, working_dir = ?, tmux_name = ?, "
            "agent_type = ?, agent_family = ?, agent_family_source = ?, title = ?, last_work_at = ?, "
            "tmux_created_epoch = ?, lifecycle = ?, lifecycle_source = ?, last_seen_running_at = ?, updated_at = ? "
            "WHERE id = ? AND origin = ? AND host_key = ?",
            (*wanted, lifecycle, sleep_source, now, now, sid, PEER_ORIGIN, host_key))
    if conn.execute("SELECT 1 FROM peer_sessions WHERE host_key = ? AND peer_session_uuid = ? AND peer_row_id IS ? "
                    "AND peer_name = ? AND session_id = ?",
                    (host_key, peer_uuid, row.get("row_id"), name, sid)).fetchone() is None:
        conn.execute(
            "INSERT INTO peer_sessions (host_key, peer_session_uuid, peer_row_id, peer_name, session_id) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(host_key, peer_session_uuid) DO UPDATE SET "
            "peer_row_id = excluded.peer_row_id, peer_name = excluded.peer_name",
            (host_key, peer_uuid, row.get("row_id"), name, sid))
    return sid


def _finish(conn: sqlite3.Connection, *, host_key: str, asleep: Optional[Sequence[Mapping[str, object]]], skipped: int,
            complete: bool, rested: list, seen: list, now: str) -> None:
    if asleep is not None and not skipped:
        marks = ",".join("?" * len(rested))
        conn.execute(
            f"UPDATE sessions SET lifecycle_source = NULL, tmux_created_epoch = NULL "
            f"WHERE origin = ? AND host_key = ? AND lifecycle = ? "
            f"AND lifecycle_source IN ({','.join('?' * len(SLEEP_SOURCES))}) AND id NOT IN ({marks})",
            (PEER_ORIGIN, host_key, SESSION_LIFECYCLE_STOPPED, *SLEEP_SOURCES, *rested))
    if complete and not skipped:
        _prune(conn, host_key)
        marks = ",".join("?" * len(seen))
        conn.execute(
            f"UPDATE sessions SET lifecycle = ?, tmux_created_epoch = NULL, updated_at = ? "
            f"WHERE origin = ? AND host_key = ? AND lifecycle = ? AND id NOT IN ({marks})",
            (SESSION_LIFECYCLE_STOPPED, now, PEER_ORIGIN, host_key, SESSION_LIFECYCLE_RUNNING, *seen))


def _prune(conn: sqlite3.Connection, host_key: str) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=PRUNE_GRACE_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for sid, source in conn.execute("SELECT id, lifecycle_source FROM sessions WHERE origin = ? AND host_key = ? "
                                    "AND lifecycle = ? AND updated_at < ?",
                                    (PEER_ORIGIN, host_key, SESSION_LIFECYCLE_STOPPED, cutoff)).fetchall():
        if source not in SLEEP_SOURCES:
            conn.execute(
                "UPDATE swarm_agents SET session_row_id = NULL WHERE session_row_id = ? AND torn_down_at IS NOT NULL", (sid,))
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


def resolve_relayed_project(conn: sqlite3.Connection, project_uid: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    if not isinstance(project_uid, str) or not UID_RE.fullmatch(project_uid):
        return None, None
    found = conn.execute(
        "SELECT id, display_name FROM projects WHERE uid = ? ORDER BY id ASC LIMIT 1",
        (project_uid,),
    ).fetchone()
    if found is None:
        return None, None
    return int(found[0]), str(found[1]) if found[1] is not None else None


def remove_peer(conn: sqlite3.Connection, host_key: str) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM peer_sessions WHERE host_key = ?", (host_key,))
        conn.execute("UPDATE sessions SET lifecycle = ? WHERE origin = ? AND host_key = ? AND lifecycle = ?",
                     (SESSION_LIFECYCLE_STOPPED, PEER_ORIGIN, host_key, SESSION_LIFECYCLE_RUNNING))
        for (sid,) in conn.execute("SELECT id FROM sessions WHERE origin = ? AND host_key = ?",
                                   (PEER_ORIGIN, host_key)).fetchall():
            _try_delete(conn, "DELETE FROM sessions WHERE id = ?", (sid,))
        _drop_projects(conn, host_key)

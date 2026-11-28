
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import structlog

from src.core.db import transaction
from src.core.db_models import SESSION_ATTRIBUTION_DERIVED_DEEPEST, SESSION_LIFECYCLE_RUNNING, SESSION_LIFECYCLE_STOPPED
from src.core.federation import shadow_rows
from src.core.federation.shadow_rows import PEER_ORIGIN, PRUNE_GRACE_SECONDS, Shadow
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.hosts.identity import PEER_ROOT_SCHEME
from src.core.hosts.remote_project import UID_RE, ProjectIndex, lookup_remote_project
from src.core.project_lineage.peer_parents import merge_peer_project_parents, read_peer_project_parents
from src.core.project_tombstones import tombstoned_roots
from src.core.session_project_binding import BINDING_MATCHED, ProjectBinding
from src.core.session_sleep import SLEEP_SOURCES

logger = structlog.get_logger()

CHUNK = 900


@dataclass
class _Decision:

    row: Mapping[str, object]
    sleep_source: Optional[str]
    name: str
    local_uuid: str
    wanted: tuple
    lifecycle: str
    sid: Optional[int]
    clean: bool
    project_id: Optional[int]
    project_name: Optional[str]


@dataclass
class _Plan:

    decisions: List[_Decision] = field(default_factory=list)
    skipped: int = 0
    full: bool = False
    writes: bool = False
    out: Dict[str, Shadow] = field(default_factory=dict)
    seen: List[int] = field(default_factory=list)
    rested: List[int] = field(default_factory=list)


def _same(a: object, b: object) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return type(a) is type(b) and type(a) in (str, int) and a == b


def _chunks(items: Sequence[Any]) -> List[Sequence[Any]]:
    return [items[i:i + CHUNK] for i in range(0, len(items), CHUNK)]


def _tail_writes(conn: sqlite3.Connection, host_key: str, shadows: Mapping[int, tuple], plan: _Plan, complete: bool,
                 asleep: Optional[Sequence[Mapping[str, object]]]) -> bool:
    seen, rested = set(plan.seen), set(plan.rested)
    stopped = SESSION_LIFECYCLE_STOPPED
    if asleep is not None and not plan.skipped and any(
            r[2] == stopped and r[3] in SLEEP_SOURCES and r[0] not in rested for r in shadows.values()):
        return True
    if complete and not plan.skipped:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=PRUNE_GRACE_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if any(r[2] == stopped and isinstance(r[14], str) and r[14] < cutoff and r[3] not in SLEEP_SOURCES for r in shadows.values()):
            return True
        if conn.execute("SELECT 1 FROM projects WHERE host_key = ? AND root LIKE ? AND id NOT IN "
                        "(SELECT project_id FROM sessions WHERE project_id IS NOT NULL) LIMIT 1",
                        (host_key, f"{PEER_ROOT_SCHEME}%")).fetchone() is not None:
            return True
        if any(r[2] == SESSION_LIFECYCLE_RUNNING and r[0] not in seen for r in shadows.values()):
            return True
    return False


def _plan(conn: sqlite3.Connection, host_key: str, peer_install_id: str, rows: Sequence[Mapping[str, object]], complete: bool,
          asleep: Optional[Sequence[Mapping[str, object]]], log: bool) -> _Plan:
    plan = _Plan()
    live = {str(r.get("session_uuid")) for r in rows}
    todo = [(r, None) for r in rows] + [(r, r.get("source")) for r in (asleep or ()) if str(r.get("session_uuid")) not in live
                                         and r.get("source") in SLEEP_SOURCES]
    usable_rows = [(r, s) for r, s in todo if shadow_rows.usable(r)]
    peer_uuids = [str(r["session_uuid"]) for r, _ in usable_rows]
    if len(set(peer_uuids)) != len(peer_uuids):
        plan.full = True
        return plan
    shadows = {int(r[0]): tuple(r) for r in conn.execute(
        "SELECT id, session_uuid, lifecycle, lifecycle_source, project_id, project_attribution, working_dir, tmux_name, "
        "agent_type, agent_family, agent_family_source, title, last_work_at, tmux_created_epoch, updated_at "
        "FROM sessions WHERE origin = ? AND host_key = ?",
        (PEER_ORIGIN, host_key))}
    by_local = {r[1]: r[0] for r in shadows.values()}
    epoch_holders = {(r[7], r[13]): r[0] for r in shadows.values() if r[7] is not None and r[13] is not None}
    lines = {r[0]: (r[1], r[2], int(r[3])) for r in conn.execute(
        "SELECT peer_session_uuid, peer_row_id, peer_name, session_id FROM peer_sessions WHERE host_key = ?", (host_key,))}
    homes: Dict[str, int] = {}
    for part in _chunks(peer_uuids):
        homes.update({r[0]: int(r[1]) for r in conn.execute(
            f"SELECT session_uuid, project_id FROM sessions WHERE host_key = ? AND origin != ? AND project_id IS NOT NULL "
            f"AND session_uuid IN ({','.join('?' * len(part))}) ORDER BY id", (LOCAL_HOST_KEY, PEER_ORIGIN, *part))})
    names: Dict[int, str] = {}
    by_root: Dict[str, int] = {}
    for pid, root, display in conn.execute("SELECT id, root, display_name FROM projects WHERE host_key = ?", (host_key,)):
        by_root[root] = int(pid)
        names[int(pid)] = display
    uids = sorted({str(r["project_uid"]) for r, _ in usable_rows
                   if isinstance(r.get("project_uid"), str) and UID_RE.fullmatch(r["project_uid"])})
    by_uid: Dict[str, Tuple[int, str]] = {}
    for part in _chunks(uids):
        for pid, root, display, uid in conn.execute(
                f"SELECT id, root, display_name, uid FROM projects WHERE uid IN ({','.join('?' * len(part))})", tuple(part)):
            by_uid[uid] = (int(pid), root)
            names[int(pid)] = display
    missing = sorted({h for h in homes.values() if h not in names})
    for part in _chunks(missing):
        names.update({int(r[0]): r[1] for r in conn.execute(
            f"SELECT id, display_name FROM projects WHERE id IN ({','.join('?' * len(part))})", tuple(part))})
    index, claimed = ProjectIndex(by_uid, by_root), set()
    tombstones = tombstoned_roots(conn)
    parent_updates: Dict[str, Optional[str]] = {}
    frame_epochs: set[Tuple[str, int]] = set()
    for row, sleep_source in todo:
        lifecycle = SESSION_LIFECYCLE_STOPPED if sleep_source else SESSION_LIFECYCLE_RUNNING
        if not shadow_rows.usable(row):
            plan.skipped += 1
            if log:
                logger.info("peer_shadow_row_skipped", host=host_key, reason="unusable name, uuid, folder or label")
            continue
        name, peer_uuid = str(row["name"]), str(row["session_uuid"])
        p_root = shadow_rows.peer_project_root(host_key, str(row["working_dir"]))
        p_uid = row.get("project_uid") if isinstance(row.get("project_uid"), str) and UID_RE.fullmatch(row["project_uid"]) else None
        if p_root in tombstones and peer_uuid not in homes and (p_uid is None or p_uid not in by_uid) and p_root not in by_root:
            continue
        local_uuid = shadow_rows.shadow_uuid(peer_install_id, peer_uuid)
        if peer_uuid in homes:
            binding: Optional[ProjectBinding] = ProjectBinding(project_id=homes[peer_uuid], attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST,
                                                               rule=BINDING_MATCHED)
        else:
            binding = lookup_remote_project(index, host_key, str(row["working_dir"]),
                                            root=shadow_rows.peer_project_root(host_key, str(row["working_dir"])),
                                            project_uid=row.get("project_uid") if isinstance(row.get("project_uid"), str) else None,
                                            claimed=claimed)
        if binding is None:
            plan.full = True
            return plan
        if p_uid is not None and "parent_project_uid" in row:
            raw_parent = row.get("parent_project_uid")
            parent_updates[p_uid] = raw_parent if isinstance(raw_parent, str) and UID_RE.fullmatch(raw_parent) else None
        project_name = names.get(binding.project_id) if binding.project_id is not None else None
        epoch = shadow_rows.clean_epoch(row.get("tmux_created_epoch"))
        wanted = (
            binding.project_id, binding.attribution, row["working_dir"], name, row.get("agent_type"),
            row.get("agent_family"), row.get("agent_family_source") or "unknown", row.get("label"),
            shadow_rows.clean_stamp(row.get("last_work_at")), epoch,
        )
        line = lines.get(peer_uuid)
        sid = line[2] if line is not None else by_local.get(local_uuid)
        if epoch is not None:
            ekey = (name, epoch)
            if ekey in frame_epochs or (ekey in epoch_holders and epoch_holders[ekey] != sid):
                plan.full = True
                return plan
            frame_epochs.add(ekey)
        stored = shadows.get(sid) if sid is not None else None
        clean = (line is not None and stored is not None and line[2] == sid and stored[2] == lifecycle
                 and _same(stored[3], sleep_source)
                 and all(_same(a, b) for a, b in zip(wanted, stored[4:14]))
                 and _same(line[0], row.get("row_id")) and _same(line[1], name))
        plan.decisions.append(_Decision(row, sleep_source, name, local_uuid, wanted, lifecycle, sid, clean, binding.project_id, project_name))
    if parent_updates:
        current_parents = read_peer_project_parents(conn)
        if merge_peer_project_parents(current_parents, parent_updates) != current_parents:
            plan.full = True
            return plan
    sids = [d.sid for d in plan.decisions if d.sid is not None]
    if len(set(sids)) != len(sids):
        plan.full = True
        return plan
    plan.writes = any(not d.clean for d in plan.decisions)
    if not plan.writes:
        for d in plan.decisions:
            (plan.rested if d.sleep_source else plan.seen).append(d.sid)
            if not d.sleep_source:
                plan.out[d.name] = Shadow(d.sid, d.project_id, d.project_name)
        plan.writes = _tail_writes(conn, host_key, shadows, plan, complete, asleep)
    return plan


def _read_plan(conn: sqlite3.Connection, host_key: str, peer_install_id: str, rows: Sequence[Mapping[str, object]],
               complete: bool, asleep: Optional[Sequence[Mapping[str, object]]], log: bool) -> _Plan:
    conn.execute("BEGIN")
    try:
        plan = _plan(conn, host_key, peer_install_id, rows, complete, asleep, log)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return plan


def _apply(conn: sqlite3.Connection, plan: _Plan, *, host_key: str, complete: bool, asleep: Optional[Sequence[Mapping[str, object]]],
           now: str) -> Dict[str, Shadow]:
    out: Dict[str, Shadow] = {}
    seen: List[int] = []
    rested: List[int] = []
    for d in plan.decisions:
        sid = d.sid if d.clean else shadow_rows._upsert_row(
            conn, host_key=host_key, sid=d.sid, row=d.row, name=d.name, local_uuid=d.local_uuid, wanted=d.wanted,
            lifecycle=d.lifecycle, sleep_source=d.sleep_source, now=now)
        if d.sleep_source:
            rested.append(sid)
            continue
        seen.append(sid)
        out[d.name] = Shadow(sid, d.project_id, d.project_name)
    shadow_rows._finish(conn, host_key=host_key, asleep=asleep, skipped=plan.skipped, complete=complete, rested=rested, seen=seen, now=now)
    return out


def sync_peer_diff(conn: sqlite3.Connection, *, host_key: str, peer_install_id: str, rows: Sequence[Mapping[str, object]],
                   complete: bool, asleep: Optional[Sequence[Mapping[str, object]]] = None) -> Dict[str, Shadow]:
    now = shadow_rows.utc_now()
    kwargs = dict(host_key=host_key, peer_install_id=peer_install_id, rows=rows, complete=complete, asleep=asleep)
    try:
        plan = _read_plan(conn, host_key, peer_install_id, rows, complete, asleep, False)
    except sqlite3.Error as exc:
        logger.warning("peer_shadow_diff_fallback", host=host_key, error_type=type(exc).__name__)
        return shadow_rows.full_sync(conn, **kwargs)
    if plan.full:
        return shadow_rows.full_sync(conn, **kwargs)
    if not plan.writes:
        _log_skips(plan.skipped, host_key)
        return plan.out
    with transaction(conn):
        plan = _plan(conn, host_key, peer_install_id, rows, complete, asleep, True)
        if not plan.full:
            return _apply(conn, plan, host_key=host_key, complete=complete, asleep=asleep, now=now)
    return shadow_rows.full_sync(conn, **kwargs)


def _log_skips(skipped: int, host_key: str) -> None:
    for _ in range(skipped):
        logger.info("peer_shadow_row_skipped", host=host_key, reason="unusable name, uuid, folder or label")

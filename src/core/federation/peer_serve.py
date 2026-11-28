
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from src.core import session_sleep
from src.core.computers import direction
from src.core.db import get_meta, table_exists
from src.core.db_models import META_INSTALL_ID
from src.core.federation import peer_hosts
from src.core.federation.shadow_rows import MAX_ROWS, PEER_ORIGIN
from src.core.hosts.ddl import HOST_STATE_UP, LOCAL_HOST_KEY
from src.core.hosts.identity import REMOTE_ID_PREFIX
from src.core.project_lineage.parents import parent_project_ids
from src.core.worktrees.store import WorktreeStore
from src.models import SessionInfo

StampDetail = Tuple[str, Optional[str], Optional[str], Optional[int]]
ProjectUids = Tuple[Optional[str], Optional[str], Optional[str]]


def owned_rows(infos: List[SessionInfo]) -> List[SessionInfo]:
    return [i for i in infos
            if i.host_key == LOCAL_HOST_KEY and not str(i.session.id).startswith(REMOTE_ID_PREFIX)
            and i.origin_install_id is None]


def _stamp_lookup(conn: sqlite3.Connection, rows: List[SessionInfo]) -> Dict[int, StampDetail]:
    ids = sorted({i.session_row_id for i in rows if i.session_row_id is not None})
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {
        int(r[0]): (str(r[1]), r[2], r[3], int(r[4]) if r[4] is not None else None)
        for r in conn.execute(
            f"SELECT id, session_uuid, claude_title, last_work_at, tmux_created_epoch "
            f"FROM sessions WHERE host_key = 'local' AND id IN ({marks})",
            ids,
        )
    }


def _worktree_parents_for_db(conn: sqlite3.Connection) -> Dict[str, str]:
    row = conn.execute("PRAGMA database_list").fetchone()
    db_file = row[2] if row and len(row) > 2 else ""
    if not db_file:
        return {}
    return WorktreeStore(Path(db_file).parent).repo_by_path()


def _project_uid_lookup(conn: sqlite3.Connection, project_ids: Iterable[Optional[int]]) -> Dict[int, ProjectUids]:
    wanted = {int(pid) for pid in project_ids if pid is not None}
    if not wanted:
        return {}
    all_rows = [
        {
            "id": int(r[0]),
            "root": r[1],
            "host_key": r[2],
            "archived_at": r[3],
            "uid": r[4],
            "company_uid": r[5],
        }
        for r in conn.execute(
            "SELECT p.id, p.root, p.host_key, p.archived_at, p.uid, c.uid "
            "FROM projects p LEFT JOIN companies c ON c.id = p.company_id"
        )
    ]
    parents = parent_project_ids(all_rows, _worktree_parents_for_db(conn))
    uid_by_id = {row["id"]: row["uid"] for row in all_rows}
    out: Dict[int, ProjectUids] = {}
    for row in all_rows:
        pid = row["id"]
        if pid in wanted:
            parent_id = parents.get(pid)
            parent_uid = uid_by_id.get(parent_id) if parent_id is not None else None
            out[pid] = (row["uid"], row["company_uid"], parent_uid)
    return out


def _uid_lookup(conn: sqlite3.Connection, rows: List[SessionInfo]) -> Dict[int, ProjectUids]:
    return _project_uid_lookup(conn, (i.project_id for i in rows))


def _swarm_agent_roles(conn: sqlite3.Connection) -> Dict[int, str]:
    if not table_exists(conn, "swarm_agents"):
        return {}
    return {
        int(r[0]): str(r[1])
        for r in conn.execute(
            "SELECT session_row_id, rank FROM swarm_agents WHERE torn_down_at IS NULL AND session_row_id IS NOT NULL"
        )
    }


def _swarm_agent_row_ids(conn: sqlite3.Connection) -> Set[int]:
    return set(_swarm_agent_roles(conn))


def _caller_withheld(conn: sqlite3.Connection, caller_install_id: Optional[str]) -> bool:
    if not caller_install_id:
        return False
    return direction.contained(caller_install_id) or not direction.inbound_allowed(conn, caller_install_id)


def serve_to_peer(
    infos: List[SessionInfo],
    open_db: Callable[[], sqlite3.Connection],
    *,
    include_swarm: bool = False,
    caller_install_id: Optional[str] = None,
) -> List[SessionInfo]:
    kept = owned_rows(infos)
    with closing(open_db()) as conn:
        if _caller_withheld(conn, caller_install_id):
            return []
        install_id = get_meta(conn, META_INSTALL_ID)
        swarm_roles = _swarm_agent_roles(conn)
        if swarm_roles and not include_swarm:
            kept = [i for i in kept if i.session_row_id not in swarm_roles]
        stamps = _stamp_lookup(conn, kept)
        uids = _uid_lookup(conn, kept)
    return [
        _slim(
            i,
            install_id,
            stamps.get(i.session_row_id),
            uids.get(i.project_id, (None, None, None)),
            swarm_role=swarm_roles.get(i.session_row_id) if (include_swarm and i.session_row_id is not None) else None,
        )
        for i in kept
    ]


def serve_asleep_to_peer(
    open_db: Callable[[], sqlite3.Connection],
    *,
    include_swarm: bool = False,
    caller_install_id: Optional[str] = None,
) -> List[Dict[str, object]]:
    with closing(open_db()) as conn:
        if _caller_withheld(conn, caller_install_id):
            return []
        install_id = get_meta(conn, META_INSTALL_ID)
        swarm_roles = _swarm_agent_roles(conn)
        rows = session_sleep.asleep_rows(conn)
        kept = [
            r for r in rows
            if r.get("host_key", LOCAL_HOST_KEY) == LOCAL_HOST_KEY
            and r.get("origin") != PEER_ORIGIN
            and (include_swarm or r.get("id") not in swarm_roles)
        ]
        uids = _project_uid_lookup(conn, (r.get("project_id") for r in kept))
    out: List[Dict[str, object]] = []
    for r in kept:
        puid, _cuid, parent_puid = uids.get(r.get("project_id"), (None, None, None))
        epoch = r.get("tmux_created_epoch")
        row_id = r.get("id")
        role = swarm_roles.get(int(row_id)) if (include_swarm and row_id is not None) else None
        item: Dict[str, object] = {
            "origin_install_id": install_id,
            "session_uuid": r["session_uuid"],
            "tmux_session": r.get("tmux_name"),
            "label": r.get("title"),
            "working_dir": r.get("working_dir"),
            "agent_type": r.get("agent_type"),
            "agent_family": r.get("agent_family"),
            "agent_family_source": r.get("agent_family_source"),
            "project_uid": puid,
            "parent_project_uid": parent_puid,
            "last_work_at": r.get("last_work_at"),
            "tmux_created_epoch": int(epoch) if epoch is not None else None,
            "source": r.get("lifecycle_source") if r.get("lifecycle_source") in session_sleep.SLEEP_SOURCES
            else session_sleep.LIFECYCLE_SOURCE_SLEPT,
        }
        if include_swarm:
            item["is_swarm"] = role is not None
            item["swarm_role"] = role
        out.append(item)
    return out


def _origin_peer_uuids(conn: sqlite3.Connection, host_key: str) -> Dict[int, str]:
    if not table_exists(conn, "peer_sessions"):
        return {}
    return {
        int(r[0]): str(r[1])
        for r in conn.execute(
            "SELECT session_id, peer_session_uuid FROM peer_sessions WHERE host_key = ?",
            (host_key,),
        )
    }


def _slim_relayed(
    info: SessionInfo,
    *,
    origin_install_id: str,
    origin_label: str,
    origin_uuid: Optional[str],
) -> SessionInfo:
    relayed_host_key = peer_hosts.host_key_for(origin_install_id)
    return info.model_copy(update={
        "origin_install_id": origin_install_id,
        "origin_label": origin_label,
        "hop": 1,
        "host_key": relayed_host_key,
        "host_label": origin_label,
        "host_state": HOST_STATE_UP,
        "session_uuid": origin_uuid or info.session_uuid,
        "session": info.session.model_copy(update={"pty_pid": None}),
        "local_servers": [],
        "parent_session_id": None,
        "project_id": None,
        "project_name": None,
        "session_row_id": None,
        "swarm_agent_id": None,
    })


def serve_relayed_to_peer(
    peer_snapshots: Mapping[str, Sequence[SessionInfo]],
    open_db: Callable[[], sqlite3.Connection],
    *,
    caller_install_id: Optional[str] = None,
    connected_peer_ids: Optional[Iterable[str]] = None,
    include_swarm: bool = False,
    withheld_peer_ids: Optional[Iterable[str]] = None,
) -> List[SessionInfo]:
    if not peer_snapshots:
        return []
    connected_set = set(connected_peer_ids) if connected_peer_ids is not None else None
    withheld_set = set(withheld_peer_ids or ())
    out: List[SessionInfo] = []
    with closing(open_db()) as conn:
        if _caller_withheld(conn, caller_install_id):
            return []
        self_install_id = get_meta(conn, META_INSTALL_ID)
        peers_by_id = {p.peer_install_id: p for p in peer_hosts.list_peers(conn, include_mesh=True)}
        for origin_iid, rows in peer_snapshots.items():
            if not origin_iid or origin_iid == caller_install_id or origin_iid == self_install_id:
                continue
            peer = peers_by_id.get(origin_iid)
            if peer is None:
                continue
            if connected_set is not None and origin_iid not in connected_set:
                continue
            if (
                origin_iid in withheld_set
                or direction.contained(origin_iid)
                or direction.is_one_way_toward(origin_iid)
                or not direction.inbound_allowed(conn, origin_iid)
            ):
                continue
            origin_uuids = _origin_peer_uuids(conn, peer.key)
            for info in list(rows)[:MAX_ROWS]:
                if getattr(info, "hop", 0) != 0:
                    continue
                if info.origin_install_id != origin_iid:
                    continue
                if getattr(info, "is_swarm", False) and not include_swarm:
                    continue
                orig_uuid = origin_uuids.get(info.session_row_id) if info.session_row_id is not None else None
                out.append(
                    _slim_relayed(
                        info,
                        origin_install_id=origin_iid,
                        origin_label=peer.label,
                        origin_uuid=orig_uuid,
                    )
                )
    return out


def _slim(
    info: SessionInfo,
    install_id: object,
    detail: StampDetail | tuple[str, str | None] | str | None,
    uids: ProjectUids | tuple[str | None, str | None] = (None, None, None),
    *,
    swarm_role: Optional[str] = None,
) -> SessionInfo:
    if isinstance(detail, tuple):
        uuid = detail[0]
        title = detail[1] if len(detail) > 1 else None
        last_work_at = detail[2] if len(detail) > 2 else None
        db_epoch = detail[3] if len(detail) > 3 else None
    else:
        uuid, title, last_work_at, db_epoch = detail, None, None, None
    puid = uids[0] if len(uids) > 0 else None
    cuid = uids[1] if len(uids) > 1 else None
    parent_puid = uids[2] if len(uids) > 2 else None
    epoch = db_epoch if db_epoch is not None else info.session.tmux_created_epoch
    session_update: Dict[str, object] = {"pty_pid": None}
    if epoch is not None and info.session.tmux_created_epoch != epoch:
        session_update["tmux_created_epoch"] = epoch
    update: Dict[str, object] = {
        "origin_install_id": install_id,
        "session_uuid": uuid,
        "project_uid": puid,
        "company_uid": cuid,
        "parent_project_uid": parent_puid,
        "last_work_at": last_work_at,
        "claude_title": title,
        "session": info.session.model_copy(update=session_update),
        "local_servers": [],
        "parent_session_id": None,
        "project_id": None,
        "project_name": None,
        "swarm_agent_id": None,
        "hop": 0,
    }
    if swarm_role is not None:
        update["is_swarm"] = True
        update["swarm_role"] = swarm_role
        update["swarm_rank"] = info.swarm_rank or swarm_role
    return info.model_copy(update=update)


from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

import httpx
import pydantic
import structlog

from src.core.computers import direction
from src.core.federation import peer_hosts, peer_http, peer_links, peer_serve, shadow_rows
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.federation.peer_link import CONNECTED, CONNECTING, DISCONNECTED
from src.core.db_models import SESSION_LIFECYCLE_RUNNING
from src.core.hosts.ddl import HOST_STATE_UP, LOCAL_HOST_KEY
from src.core.hosts.identity import REMOTE_ID_PREFIX, remote_session_id
from src.models import Session, SessionInfo, SessionStatus

logger = structlog.get_logger()

DEADLINE_SECONDS = 1.5
FRESH_SECONDS = 1.5
STALE_SECONDS = 4.5
_UNKNOWN = "unknown"


@dataclass
class Snapshot:

    rows: List[SessionInfo]
    at: float = field(default_factory=time.monotonic)


_SNAPSHOTS: Dict[str, Snapshot] = {}
_OWNER_IDS: Dict[str, Dict[str, str]] = {}


def owner_session_id(peer_key: str, tmux_name: str) -> Optional[str]:
    return _OWNER_IDS.get(peer_key, {}).get(tmux_name)
_INFLIGHT: Dict[str, "asyncio.Task[None]"] = {}
_FAILED: Dict[str, float] = {}


def reset() -> None:
    _SNAPSHOTS.clear()
    _OWNER_IDS.clear()
    _INFLIGHT.clear()
    _FAILED.clear()


def forget(peer_install_id: str) -> None:
    _SNAPSHOTS.pop(peer_install_id, None)
    _INFLIGHT.pop(peer_install_id, None)
    _FAILED.pop(peer_install_id, None)


def accept(raw: Any, peer_install_id: str) -> bool:
    if not isinstance(raw, Mapping):
        return False
    session = raw.get("session")
    sid = str(session.get("id", "")) if isinstance(session, Mapping) else ""
    return (raw.get("origin_install_id") == peer_install_id and raw.get("host_key", LOCAL_HOST_KEY) == LOCAL_HOST_KEY
            and bool(sid) and not sid.startswith(REMOTE_ID_PREFIX))


def _to_info(raw: Mapping[str, Any], shadow: shadow_rows.Shadow, peer: "peer_hosts.PeerRow") -> SessionInfo:
    info = SessionInfo.model_validate(raw)
    name = str(info.tmux_session or "")
    session = info.session.model_copy(update={"id": remote_session_id(peer.key, name), "pty_pid": None})
    return info.model_copy(update={
        "session": session, "host_key": peer.key, "host_label": peer.label, "host_state": HOST_STATE_UP,
        "session_row_id": shadow.session_id, "parent_session_id": None, "project_id": shadow.project_id,
        "project_name": shadow.project_name, "local_servers": [], "origin_install_id": peer.peer_install_id,
        "session_uuid": shadow_rows.shadow_uuid(peer.peer_install_id, str(raw.get("session_uuid")))})


def _sync_row(raw: Mapping[str, Any]) -> Dict[str, Any]:
    session = raw.get("session") if isinstance(raw.get("session"), Mapping) else {}
    return {"session_uuid": raw.get("session_uuid"), "row_id": raw.get("session_row_id"), "name": raw.get("tmux_session"),
            "working_dir": session.get("working_dir"), "label": raw.get("label"), "agent_type": raw.get("agent_type"),
            "agent_family": raw.get("agent_family"), "agent_family_source": raw.get("agent_family_source")}


def _import(open_db: Callable[[], sqlite3.Connection], peer: "peer_hosts.PeerRow", data: Any) -> Optional[List[SessionInfo]]:
    if not isinstance(data, list):
        return None
    accepted = [raw for raw in data[:shadow_rows.MAX_ROWS] if accept(raw, peer.peer_install_id)]
    with closing(open_db()) as conn:
        own = _own_uuids(conn, accepted)
        accepted = [raw for raw in accepted if str(raw.get("session_uuid")) not in own]
        shadows = shadow_rows.sync_peer(conn, host_key=peer.key, peer_install_id=peer.peer_install_id,
                                        rows=[_sync_row(raw) for raw in accepted], complete=len(accepted) == len(data))
    _OWNER_IDS[peer.key] = {str(raw.get("tmux_session")): str(raw["session"]["id"]) for raw in accepted}
    rows: List[SessionInfo] = []
    for raw in accepted:
        shadow = shadows.get(str(raw.get("tmux_session")))
        try:
            if shadow is None:
                raise ValueError("no shadow row")
            rows.append(_to_info(raw, shadow, peer))
        except (pydantic.ValidationError, ValueError) as exc:
            logger.warning("peer_listing_row_dropped", peer=peer.key, error_type=type(exc).__name__)
    return rows


def _own_uuids(conn: sqlite3.Connection, accepted: List[Any]) -> set:
    ids = sorted({str(raw.get("session_uuid")) for raw in accepted})
    if not ids:
        return set()
    marks = ",".join("?" * len(ids))
    return {r[0] for r in conn.execute(
        f"SELECT session_uuid FROM sessions WHERE host_key = ? AND lifecycle = ? AND session_uuid IN ({marks})",
        (LOCAL_HOST_KEY, SESSION_LIFECYCLE_RUNNING, *ids))}


def _parse_and_import(open_db: Callable[[], sqlite3.Connection], peer: "peer_hosts.PeerRow", body: Any) -> Optional[List[SessionInfo]]:
    return _import(open_db, peer, body.json())


async def _fetch(peer: "peer_hosts.PeerRow", client: Any, open_db: Callable[[], sqlite3.Connection]) -> None:
    key = peer.peer_install_id
    try:
        response = await asyncio.wait_for(client.request("GET", "/sessions/list", max_body=peer_http.MAX_LISTING_BODY),
                                          DEADLINE_SECONDS)
        rows = None
        if response.status_code == 200:
            rows = await asyncio.to_thread(_parse_and_import, open_db, peer, response)
    except (PeerUnreachable, PeerRefused, asyncio.TimeoutError, httpx.HTTPError, sqlite3.Error):
        logger.info("peer_listing_unavailable", peer=peer.key)
        rows = None
    except Exception as exc:  # noqa: BLE001
        logger.warning("peer_listing_fetch_failed", peer=peer.key, error_type=type(exc).__name__)
        rows = None
    if rows is None:
        _FAILED[key] = time.monotonic()
    else:
        _SNAPSHOTS[key] = Snapshot(rows)


async def refresh(peer: "peer_hosts.PeerRow", links: "peer_links.PeerLinks",
                  open_db: Callable[[], sqlite3.Connection], *, force: bool = False) -> None:
    client = links.client(peer.peer_install_id)
    if client is None:
        return
    key, now = peer.peer_install_id, time.monotonic()
    task = _INFLIGHT.get(key)
    if task is None or task.done() or task.get_loop() is not asyncio.get_running_loop():
        snap = _SNAPSHOTS.get(key)
        if not force and ((snap is not None and now - snap.at < FRESH_SECONDS) or now - _FAILED.get(key, -1e9) < FRESH_SECONDS):
            return
        task = _INFLIGHT[key] = asyncio.get_running_loop().create_task(_fetch(peer, client, open_db))
    await asyncio.shield(task)


def _cold_rows(open_db: Callable[[], sqlite3.Connection], peer: "peer_hosts.PeerRow") -> List[SessionInfo]:
    with closing(open_db()) as conn:
        found = conn.execute(
            "SELECT s.id, s.session_uuid, s.tmux_name, s.working_dir, s.title, s.agent_type, s.agent_family, "
            "s.project_id, p.display_name FROM sessions s LEFT JOIN projects p ON p.id = s.project_id "
            "WHERE s.host_key = ? AND s.origin = ? AND s.lifecycle = 'running' AND s.tmux_name IS NOT NULL",
            (peer.key, shadow_rows.PEER_ORIGIN)).fetchall()
    return [SessionInfo(
        session=Session(id=remote_session_id(peer.key, r[2]), working_dir=r[3] or "/", status=SessionStatus.RUNNING),
        tmux_session=r[2], label=r[4], agent_type=r[5], agent_family=r[6], session_row_id=r[0], project_id=r[7],
        project_name=r[8], host_key=peer.key, host_label=peer.label, session_uuid=r[1],
        origin_install_id=peer.peer_install_id) for r in found]


def _state_word(state: str) -> str:
    if state == CONNECTED:
        return HOST_STATE_UP
    return DISCONNECTED if state in (CONNECTING, DISCONNECTED) else state


_UNMEASURED = ("activity_hint", "parked_summary", "workflow_active", "subagents_state", "subagents_running",
               "subagents_total", "timers_state", "timers_live", "timers_next_fire_at", "automations_state", "automations_total",
               "automations_enabled", "automations_next", "skills_state", "skills_fired",
               "skill_last", "background_open", "usage_limit", "background_processes", "agent_update", "mcp_health", "stats",
               "task_lead", "do_not_disturb")


def _shown(rows: List[SessionInfo], word: str) -> List[SessionInfo]:
    if word == HOST_STATE_UP:
        return list(rows)
    blank = {name: None for name in _UNMEASURED}
    return [r.model_copy(update={"host_state": word, "activity_status": _UNKNOWN, "status_source": "none",
                                 "startup_gate": _UNKNOWN, "unread": False, **blank}) for r in rows]


async def peer_rows(open_db: Callable[[], sqlite3.Connection],
                    links: Optional["peer_links.PeerLinks"] = None, *, force: bool = False) -> List[SessionInfo]:
    links = links or peer_links.LINKS
    if links is None:
        return []
    try:
        peers = await asyncio.to_thread(_read_peers, open_db)
    except (sqlite3.Error, OSError):
        return []
    peers = [p for p in peers if not direction.is_one_way_toward(p.peer_install_id)]
    done = await asyncio.gather(*(refresh(p, links, open_db, force=force) for p in peers), return_exceptions=True)
    out: List[SessionInfo] = []
    for peer, result in zip(peers, done):
        if isinstance(result, BaseException):
            logger.warning("peer_listing_refresh_failed", peer=peer.key, error_type=type(result).__name__)
        try:
            snap = _SNAPSHOTS.get(peer.peer_install_id)
            word = _state_word(links.state(peer.peer_install_id))
            if snap is None:
                out += _shown(await _cold(open_db, peer), DISCONNECTED if word == HOST_STATE_UP else word)
            else:
                stale = time.monotonic() - snap.at > STALE_SECONDS
                out += _shown(snap.rows, DISCONNECTED if word == HOST_STATE_UP and stale else word)
        except Exception as exc:  # noqa: BLE001
            logger.warning("peer_rows_failed", peer=peer.key, error_type=type(exc).__name__)
    return out


_PEERS_CACHE: Optional[tuple] = None
_PEERS_LOCK = threading.Lock()


def _db_signature(path: str) -> Optional[tuple]:
    marks = []
    for name in (path, path + "-wal"):
        try:
            st = os.stat(name)
        except FileNotFoundError:
            marks.append(None)
            continue
        except OSError:
            return None
        marks.append((st.st_ino, st.st_mtime_ns, st.st_size))
    return None if marks[0] is None else tuple(marks)


def _read_peers(open_db: Callable[[], sqlite3.Connection]) -> List["peer_hosts.PeerRow"]:
    global _PEERS_CACHE
    with _PEERS_LOCK:
        cached = _PEERS_CACHE
        if cached is not None and cached[0] is open_db:
            sig = _db_signature(cached[1])
            if sig is not None and sig == cached[2]:
                return list(cached[3])
    with closing(open_db()) as conn:
        row = conn.execute("PRAGMA database_list").fetchone()
        path = row[2] if row and len(row) > 2 else ""
        sig = _db_signature(path) if path else None
        peers = peer_hosts.list_peers(conn)
    with _PEERS_LOCK:
        _PEERS_CACHE = (open_db, path, sig, peers) if sig is not None else None
    return list(peers)


async def _cold(open_db: Callable[[], sqlite3.Connection], peer: "peer_hosts.PeerRow") -> List[SessionInfo]:
    try:
        return await asyncio.to_thread(_cold_rows, open_db, peer)
    except (sqlite3.Error, OSError) as exc:
        logger.info("peer_cold_rows_unreadable", peer=peer.key, reason=type(exc).__name__)
        return []


async def for_caller(infos: List[SessionInfo], *, is_peer: bool, open_db: Callable[[], sqlite3.Connection],
                     links: Optional["peer_links.PeerLinks"] = None) -> List[SessionInfo]:
    if is_peer:
        return await asyncio.to_thread(peer_serve.serve_to_peer, infos, open_db)
    return infos + await peer_rows(open_db, links)

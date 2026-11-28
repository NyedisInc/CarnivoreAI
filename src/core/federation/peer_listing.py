
from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
import time
from types import SimpleNamespace
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set

import httpx
import pydantic
import structlog

from src.core.computers import direction
from src.core.db import get_meta
from src.core.db_models import META_INSTALL_ID, SESSION_LIFECYCLE_RUNNING
from src.core.federation import import_lane, mesh_peers, peer_hosts, peer_http, peer_links, peer_serve, shadow_rows
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.federation.peer_link import CONNECTED, CONNECTING, DISCONNECTED
from src.core.pack.machines import capabilities
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
_RELAYED_SNAPSHOTS: Dict[str, Dict[str, Snapshot]] = {}
PUSHED: set = set()
_PUSHED_AT: Dict[str, float] = {}
_OWNER_IDS: Dict[str, Dict[str, str]] = {}


def owner_session_id(peer_key: str, tmux_name: str) -> Optional[str]:
    return _OWNER_IDS.get(peer_key, {}).get(tmux_name)
_INFLIGHT: Dict[str, "asyncio.Task[None]"] = {}
_FAILED: Dict[str, float] = {}


def reset() -> None:
    _SNAPSHOTS.clear()
    _RELAYED_SNAPSHOTS.clear()
    PUSHED.clear()
    _PUSHED_AT.clear()
    _OWNER_IDS.clear()
    _INFLIGHT.clear()
    _FAILED.clear()
    _NO_ASLEEP.clear()


def forget(peer_install_id: str) -> None:
    _SNAPSHOTS.pop(peer_install_id, None)
    _RELAYED_SNAPSHOTS.pop(peer_install_id, None)
    PUSHED.discard(peer_install_id)
    _PUSHED_AT.pop(peer_install_id, None)
    _INFLIGHT.pop(peer_install_id, None)
    _FAILED.pop(peer_install_id, None)


def accept(raw: Any, peer_install_id: str) -> bool:
    if not isinstance(raw, Mapping):
        return False
    session = raw.get("session")
    sid = str(session.get("id", "")) if isinstance(session, Mapping) else ""
    return (raw.get("origin_install_id") == peer_install_id and raw.get("host_key", LOCAL_HOST_KEY) == LOCAL_HOST_KEY
            and raw.get("hop", 0) == 0 and type(raw.get("hop", 0)) is int
            and bool(sid) and not sid.startswith(REMOTE_ID_PREFIX))


def accept_relayed(
    raw: Any,
    *,
    self_install_id: Optional[str],
    hub_install_id: str,
    direct_peer_ids: Set[str],
) -> bool:
    if not isinstance(raw, Mapping):
        return False
    if type(raw.get("hop")) is not int or raw.get("hop") != 1:
        return False
    origin_iid = raw.get("origin_install_id")
    if not isinstance(origin_iid, str) or not origin_iid:
        return False
    if origin_iid == hub_install_id or (self_install_id is not None and origin_iid == self_install_id):
        return False
    if origin_iid in direct_peer_ids:
        return False
    if direction.contained(origin_iid) or direction.is_one_way_toward(origin_iid):
        return False
    tmux = raw.get("tmux_session")
    if not isinstance(tmux, str) or not (0 < len(tmux) <= shadow_rows.MAX_NAME) or ":" in tmux:
        return False
    session = raw.get("session")
    sid = session.get("id") if isinstance(session, Mapping) else None
    return isinstance(sid, str) and bool(sid)


_REWRITTEN = {"host_key": str, "host_label": str, "host_state": str, "session_row_id": int, "parent_session_id": int, "project_id": int,
              "project_name": str, "origin_install_id": str, "session_uuid": str}
_REQUIRED = frozenset({"host_key", "host_label", "host_state"})


def _plain(value: Any, kind: type, optional: bool = True) -> bool:
    return (optional and value is None) or type(value) is kind


def _to_info_single(raw: Mapping[str, Any], shadow: shadow_rows.Shadow, peer: "peer_hosts.PeerRow") -> Optional[SessionInfo]:
    session, tmux = raw.get("session"), raw.get("tmux_session")
    if not isinstance(session, Mapping) or not (tmux is None or isinstance(tmux, str)):
        return None
    if not isinstance(session.get("id"), str) or not _plain(session.get("pty_pid"), int) or any(
            not _plain(raw.get(k), t, k not in _REQUIRED) for k, t in _REWRITTEN.items() if k in raw):
        return None
    name = tmux or ""
    return SessionInfo.model_validate({
        **raw, "session": {**session, "id": remote_session_id(peer.key, name), "pty_pid": None},
        "host_key": peer.key, "host_label": peer.label, "host_state": HOST_STATE_UP,
        "session_row_id": shadow.session_id, "parent_session_id": None, "project_id": shadow.project_id,
        "project_name": shadow.project_name, "origin_install_id": peer.peer_install_id,
        "session_uuid": shadow_rows.shadow_uuid(peer.peer_install_id, str(raw.get("session_uuid")))})


def to_info(raw: Mapping[str, Any], shadow: shadow_rows.Shadow, peer: "peer_hosts.PeerRow") -> SessionInfo:
    if capabilities.mesh_on():
        built = _to_info_single(raw, shadow, peer)
        if built is not None:
            return built
    info = SessionInfo.model_validate(raw)
    name = str(info.tmux_session or "")
    session = info.session.model_copy(update={"id": remote_session_id(peer.key, name), "pty_pid": None})
    return info.model_copy(update={
        "session": session, "host_key": peer.key, "host_label": peer.label, "host_state": HOST_STATE_UP,
        "session_row_id": shadow.session_id, "parent_session_id": None, "project_id": shadow.project_id,
        "project_name": shadow.project_name, "origin_install_id": peer.peer_install_id,
        "session_uuid": shadow_rows.shadow_uuid(peer.peer_install_id, str(raw.get("session_uuid")))})


def sync_row(raw: Mapping[str, Any]) -> Dict[str, Any]:
    session = raw.get("session") if isinstance(raw.get("session"), Mapping) else {}
    epoch = raw.get("tmux_created_epoch")
    if epoch is None:
        epoch = session.get("tmux_created_epoch")
    out: Dict[str, Any] = {
        "session_uuid": raw.get("session_uuid"),
        "row_id": raw.get("session_row_id"),
        "name": raw.get("tmux_session"),
        "working_dir": session.get("working_dir"),
        "label": raw.get("label"),
        "agent_type": raw.get("agent_type"),
        "agent_family": raw.get("agent_family"),
        "agent_family_source": raw.get("agent_family_source"),
        "project_uid": raw.get("project_uid"),
        "last_work_at": raw.get("last_work_at"),
        "tmux_created_epoch": epoch,
    }
    if "parent_project_uid" in raw:
        out["parent_project_uid"] = raw.get("parent_project_uid")
    return out


def _asleep_sync_row(raw: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "session_uuid": raw.get("session_uuid"),
        "name": raw.get("tmux_session"),
        "working_dir": raw.get("working_dir"),
        "label": raw.get("label"),
        "agent_type": raw.get("agent_type"),
        "agent_family": raw.get("agent_family"),
        "agent_family_source": raw.get("agent_family_source"),
        "project_uid": raw.get("project_uid"),
        "last_work_at": raw.get("last_work_at"),
        "tmux_created_epoch": raw.get("tmux_created_epoch"),
        "source": raw.get("source"),
    }
    if "parent_project_uid" in raw:
        out["parent_project_uid"] = raw.get("parent_project_uid")
    return out


def _import(open_db: Callable[[], sqlite3.Connection], peer: "peer_hosts.PeerRow", data: Any,
            asleep: Any = None) -> Optional[List[SessionInfo]]:
    if not isinstance(data, list):
        return None
    accepted = [raw for raw in data[:shadow_rows.MAX_ROWS] if accept(raw, peer.peer_install_id)]
    with closing(open_db()) as conn:
        own = _own_uuids(conn, accepted)
        accepted = [raw for raw in accepted if str(raw.get("session_uuid")) not in own]
        resting = None
        if isinstance(asleep, list):
            resting = [raw for raw in asleep[:shadow_rows.MAX_ROWS]
                       if isinstance(raw, Mapping) and raw.get("origin_install_id") == peer.peer_install_id]
            held = _own_uuids(conn, resting)
            resting = [row for row in (_asleep_sync_row(raw) for raw in resting if str(raw.get("session_uuid")) not in held)
                       if shadow_rows.usable(row) and not shadow_rows.JOB_WORKER_DIR.search(str(row["working_dir"]))]
        shadows = shadow_rows.sync_peer(conn, host_key=peer.key, peer_install_id=peer.peer_install_id,
                                        rows=[sync_row(raw) for raw in accepted], complete=len(accepted) == len(data),
                                        asleep=resting)
    _OWNER_IDS[peer.key] = {str(raw.get("tmux_session")): str(raw["session"]["id"]) for raw in accepted}
    rows: List[SessionInfo] = []
    for raw in accepted:
        shadow = shadows.get(str(raw.get("tmux_session")))
        try:
            if shadow is None:
                raise ValueError("no shadow row")
            rows.append(to_info(raw, shadow, peer))
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


def _to_relayed_info(
    raw: Mapping[str, Any],
    *,
    origin_install_id: str,
    origin_label: str,
    project_id: Optional[int],
    project_name: Optional[str],
) -> SessionInfo:
    info = SessionInfo.model_validate(raw)
    host_key = peer_hosts.host_key_for(origin_install_id)
    name = str(info.tmux_session or "")
    session = info.session.model_copy(update={"id": remote_session_id(host_key, name), "pty_pid": None})
    raw_uuid = raw.get("session_uuid")
    local_uuid = shadow_rows.shadow_uuid(origin_install_id, str(raw_uuid)) if isinstance(raw_uuid, str) and raw_uuid else None
    return info.model_copy(update={
        "session": session,
        "host_key": host_key,
        "host_label": origin_label,
        "host_state": HOST_STATE_UP,
        "session_row_id": None,
        "parent_session_id": None,
        "project_id": project_id,
        "project_name": project_name,
        "origin_install_id": origin_install_id,
        "origin_label": origin_label,
        "hop": 1,
        "session_uuid": local_uuid,
        "swarm_agent_id": None,
    })


def _import_relayed(
    open_db: Callable[[], sqlite3.Connection],
    hub_peer: "peer_hosts.PeerRow",
    relayed: Any,
) -> Optional[Dict[str, List[SessionInfo]]]:
    if not isinstance(relayed, list):
        return None
    with closing(open_db()) as conn:
        self_iid = get_meta(conn, META_INSTALL_ID)
        direct_ids = {p.peer_install_id for p in peer_hosts.list_peers(conn, include_mesh=True)}
        accepted = [
            raw for raw in relayed[:shadow_rows.MAX_ROWS]
            if accept_relayed(
                raw,
                self_install_id=self_iid,
                hub_install_id=hub_peer.peer_install_id,
                direct_peer_ids=direct_ids,
            )
            and direction.inbound_allowed(conn, str(raw.get("origin_install_id")))
        ]
        own = _own_uuids(conn, accepted)
        accepted = [raw for raw in accepted if str(raw.get("session_uuid")) not in own]
        proj_cache: Dict[Optional[str], tuple] = {}
        by_origin: Dict[str, List[SessionInfo]] = {}
        for raw in accepted:
            origin_iid = str(raw["origin_install_id"])
            raw_label = raw.get("origin_label") or raw.get("host_label")
            origin_label = str(raw_label)[:64] if isinstance(raw_label, str) and raw_label else origin_iid[:8]
            puid = raw.get("project_uid") if isinstance(raw.get("project_uid"), str) else None
            if puid not in proj_cache:
                proj_cache[puid] = shadow_rows.resolve_relayed_project(conn, puid)
            pid, pname = proj_cache[puid]
            try:
                built = _to_relayed_info(
                    raw,
                    origin_install_id=origin_iid,
                    origin_label=origin_label,
                    project_id=pid,
                    project_name=pname,
                )
            except (pydantic.ValidationError, ValueError) as exc:
                logger.warning("peer_relayed_row_dropped", hub=hub_peer.key, error_type=type(exc).__name__)
                continue
            by_origin.setdefault(origin_iid, []).append(built)
    return by_origin


def _parse_and_import(open_db: Callable[[], sqlite3.Connection], peer: "peer_hosts.PeerRow", body: Any,
                      asleep_body: Any = None) -> Optional[List[SessionInfo]]:
    return _import(open_db, peer, body.json(), asleep_body.json() if asleep_body is not None else None)


def _parse_and_import_full(
    open_db: Callable[[], sqlite3.Connection],
    peer: "peer_hosts.PeerRow",
    body: Any,
    asleep_body: Any = None,
) -> tuple[Optional[List[SessionInfo]], Optional[Dict[str, List[SessionInfo]]]]:
    rows = _parse_and_import(open_db, peer, body, asleep_body)
    raw_relayed = getattr(body, "relayed", None)
    relayed = _import_relayed(open_db, peer, raw_relayed) if raw_relayed is not None else None
    return rows, relayed


_NO_ASLEEP: Dict[str, float] = {}
NO_ASLEEP_SECONDS = 300.0


async def _asleep_reply(client: Any, key: str) -> Any:
    if time.monotonic() - _NO_ASLEEP.get(key, -1e9) < NO_ASLEEP_SECONDS:
        return None
    try:
        reply = await client.request("GET", "/sessions/asleep", max_body=peer_http.MAX_LISTING_BODY)
    except (PeerUnreachable, PeerRefused, httpx.HTTPError):
        return None
    if reply.status_code != 200:
        _NO_ASLEEP[key] = time.monotonic()
        return None
    return reply


_NO_MERGED: Dict[str, float] = {}


async def _merged_reply(client: Any, key: str) -> Optional[tuple]:
    if time.monotonic() - _NO_MERGED.get(key, -1e9) < NO_ASLEEP_SECONDS:
        return None
    try:
        reply = await client.request("GET", "/sessions/list-and-asleep", max_body=peer_http.MAX_LISTING_BODY)
    except (PeerUnreachable, PeerRefused, httpx.HTTPError):
        return None
    if reply.status_code != 200:
        if reply.status_code in (403, 404, 405):
            _NO_MERGED[key] = time.monotonic()
        return None
    try:
        body = await asyncio.to_thread(reply.json)
    except (ValueError, RecursionError):
        _NO_MERGED[key] = time.monotonic()
        return None
    if not isinstance(body, dict) or not isinstance(body.get("list"), list) or not isinstance(body.get("asleep"), list):
        _NO_MERGED[key] = time.monotonic()
        return None
    list_ns = SimpleNamespace(status_code=200, json=lambda: body["list"], relayed=body.get("relayed"))
    return list_ns, SimpleNamespace(status_code=200, json=lambda: body["asleep"])


def _superseded(key: str, started: float) -> bool:
    return key in PUSHED or _PUSHED_AT.get(key, -1e18) > started


async def _fetch(peer: "peer_hosts.PeerRow", client: Any, open_db: Callable[[], sqlite3.Connection]) -> None:
    key, started = peer.peer_install_id, time.monotonic()
    relayed: Optional[Dict[str, List[SessionInfo]]] = None
    try:
        merged = await asyncio.wait_for(_merged_reply(client, key), DEADLINE_SECONDS)
        if merged is not None:
            response, asleep = merged
        else:
            response, asleep = await asyncio.wait_for(asyncio.gather(
                client.request("GET", "/sessions/list", max_body=peer_http.MAX_LISTING_BODY), _asleep_reply(client, key)),
                DEADLINE_SECONDS)
        rows = None
        if _superseded(key, started):
            return
        if response.status_code == 200:
            rows, relayed = await import_lane.run(_parse_and_import_full, open_db, peer, response, asleep)
    except (PeerUnreachable, PeerRefused, asyncio.TimeoutError, httpx.HTTPError, sqlite3.Error):
        logger.info("peer_listing_unavailable", peer=peer.key)
        rows = None
    except Exception as exc:  # noqa: BLE001
        logger.warning("peer_listing_fetch_failed", peer=peer.key, error_type=type(exc).__name__)
        rows = None
    if _superseded(key, started):
        return
    if rows is None:
        _FAILED[key] = time.monotonic()
    else:
        _SNAPSHOTS[key] = Snapshot(rows)
        if relayed is not None:
            _RELAYED_SNAPSHOTS[key] = {origin: Snapshot(items) for origin, items in relayed.items()}


async def ingest_relayed(
    hub_peer: "peer_hosts.PeerRow",
    open_db: Callable[[], sqlite3.Connection],
    relayed_rows: List[Any],
) -> bool:
    try:
        relayed = await import_lane.run(_import_relayed, open_db, hub_peer, relayed_rows)
    except (sqlite3.Error, OSError, RecursionError) as exc:
        logger.info("peer_listing_relayed_import_failed", peer=hub_peer.key, error_type=type(exc).__name__)
        return False
    if relayed is None:
        return False
    _RELAYED_SNAPSHOTS[hub_peer.peer_install_id] = {origin: Snapshot(items) for origin, items in relayed.items()}
    return True


async def ingest(peer: "peer_hosts.PeerRow", open_db: Callable[[], sqlite3.Connection],
                 list_rows: List[Any], asleep_rows: List[Any]) -> bool:
    try:
        rows = await import_lane.run(_import, open_db, peer, list_rows, asleep_rows)
    except (sqlite3.Error, OSError, RecursionError) as exc:
        logger.info("peer_listing_push_import_failed", peer=peer.key, error_type=type(exc).__name__)
        return False
    if rows is None:
        return False
    _SNAPSHOTS[peer.peer_install_id] = Snapshot(rows)
    _PUSHED_AT[peer.peer_install_id] = time.monotonic()
    return True


def keep_pushed(peer_install_id: str, rows: List[SessionInfo]) -> None:
    _SNAPSHOTS[peer_install_id] = Snapshot(rows)
    _PUSHED_AT[peer_install_id] = time.monotonic()


def pushed_rows(peer_install_id: str) -> Optional[List[SessionInfo]]:
    snap = _SNAPSHOTS.get(peer_install_id)
    return None if snap is None else snap.rows


async def refresh(peer: "peer_hosts.PeerRow", links: "peer_links.PeerLinks",
                  open_db: Callable[[], sqlite3.Connection], *, force: bool = False) -> None:
    if peer.peer_install_id in PUSHED:
        return
    client = mesh_peers.session_client(links, peer.peer_install_id)
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
            "s.project_id, p.display_name, s.last_work_at, s.tmux_created_epoch "
            "FROM sessions s LEFT JOIN projects p ON p.id = s.project_id "
            "WHERE s.host_key = ? AND s.origin = ? AND s.lifecycle = 'running' AND s.tmux_name IS NOT NULL",
            (peer.key, shadow_rows.PEER_ORIGIN)).fetchall()
    return [SessionInfo(
        session=Session(id=remote_session_id(peer.key, r[2]), working_dir=r[3] or "/", status=SessionStatus.RUNNING,
                        tmux_created_epoch=r[10]),
        tmux_session=r[2], label=r[4], agent_type=r[5], agent_family=r[6], session_row_id=r[0], project_id=r[7],
        project_name=r[8], host_key=peer.key, host_label=peer.label, session_uuid=r[1],
        origin_install_id=peer.peer_install_id, last_work_at=r[9]) for r in found]


def _state_word(state: str) -> str:
    if state == CONNECTED:
        return HOST_STATE_UP
    return DISCONNECTED if state in (CONNECTING, DISCONNECTED) else state


_UNMEASURED = ("activity_hint", "parked_summary", "workflow_active", "subagents_state", "subagents_running",
               "subagents_total", "subagents_stalled", "timers_state", "timers_live", "timers_next_fire_at", "automations_state", "automations_total",
               "automations_enabled", "automations_next", "skills_state", "skills_fired",
               "skill_last", "background_open", "usage_limit", "login_expired", "background_processes", "agent_update", "mcp_health", "stats",
               "task_lead", "do_not_disturb")


def _shown(rows: List[SessionInfo], word: str) -> List[SessionInfo]:
    if word == HOST_STATE_UP:
        return list(rows)
    blank = {name: None for name in _UNMEASURED}
    return [r.model_copy(update={"host_state": word, "activity_status": _UNKNOWN, "status_source": "none",
                                 "startup_gate": _UNKNOWN, "unread": False, **blank}) for r in rows]


def _read_self_install_id(open_db: Callable[[], sqlite3.Connection]) -> Optional[str]:
    try:
        with closing(open_db()) as conn:
            return get_meta(conn, META_INSTALL_ID)
    except (sqlite3.Error, OSError):
        return None


def relayed_for_peer(
    open_db: Callable[[], sqlite3.Connection],
    links: Optional["peer_links.PeerLinks"] = None,
    *,
    caller_install_id: Optional[str] = None,
    include_swarm: bool = False,
    withheld_peer_ids: Optional[Iterable[str]] = None,
) -> List[SessionInfo]:
    links = links or peer_links.LINKS
    now = time.monotonic()
    fresh: Dict[str, List[SessionInfo]] = {}
    connected_ids: Optional[Set[str]] = set() if links is not None else None
    for origin_iid, snap in list(_SNAPSHOTS.items()):
        if now - snap.at > STALE_SECONDS and origin_iid not in PUSHED:
            continue
        if links is not None:
            if _state_word(mesh_peers.session_state(links, origin_iid)) != HOST_STATE_UP:
                continue
            connected_ids.add(origin_iid)  # type: ignore[union-attr]
        fresh[origin_iid] = list(snap.rows)
    return peer_serve.serve_relayed_to_peer(
        fresh,
        open_db,
        caller_install_id=caller_install_id,
        connected_peer_ids=connected_ids,
        include_swarm=include_swarm,
        withheld_peer_ids=withheld_peer_ids,
    )


async def peer_rows(open_db: Callable[[], sqlite3.Connection],
                    links: Optional["peer_links.PeerLinks"] = None, *, force: bool = False) -> List[SessionInfo]:
    links = links or peer_links.LINKS
    if links is None:
        return []
    try:
        all_peers = await asyncio.to_thread(read_peers, open_db, True)
    except (sqlite3.Error, OSError):
        return []
    direct_ids: Set[str] = {p.peer_install_id for p in all_peers}
    peers = [p for p in all_peers if not direction.is_one_way_toward(p.peer_install_id)]
    done = await asyncio.gather(*(refresh(p, links, open_db, force=force) for p in peers), return_exceptions=True)
    out: List[SessionInfo] = []
    connected_hubs: List[peer_hosts.PeerRow] = []
    for peer, result in zip(peers, done):
        if isinstance(result, BaseException):
            logger.warning("peer_listing_refresh_failed", peer=peer.key, error_type=type(result).__name__)
        try:
            snap = _SNAPSHOTS.get(peer.peer_install_id)
            word = _state_word(mesh_peers.session_state(links, peer.peer_install_id))
            if snap is None:
                out += _shown(await _cold(open_db, peer), DISCONNECTED if word == HOST_STATE_UP else word)
            else:
                stale = time.monotonic() - snap.at > STALE_SECONDS and peer.peer_install_id not in PUSHED
                shown_word = DISCONNECTED if word == HOST_STATE_UP and stale else word
                out += _shown(snap.rows, shown_word)
                if shown_word == HOST_STATE_UP:
                    connected_hubs.append(peer)
        except Exception as exc:  # noqa: BLE001
            logger.warning("peer_rows_failed", peer=peer.key, error_type=type(exc).__name__)
    if connected_hubs and any(_RELAYED_SNAPSHOTS.get(p.peer_install_id) for p in connected_hubs):
        self_iid = await asyncio.to_thread(_read_self_install_id, open_db)
        seen_origins: Set[str] = set(direct_ids)
        if self_iid:
            seen_origins.add(self_iid)
        now = time.monotonic()
        for hub in connected_hubs:
            for origin_iid, rsnap in list(_RELAYED_SNAPSHOTS.get(hub.peer_install_id, {}).items()):
                if origin_iid in seen_origins:
                    continue
                if direction.contained(origin_iid) or direction.is_one_way_toward(origin_iid):
                    continue
                if now - rsnap.at > STALE_SECONDS and hub.peer_install_id not in PUSHED:
                    continue
                seen_origins.add(origin_iid)
                out += list(rsnap.rows)
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


def _visible(peers: List["peer_hosts.PeerRow"], include_mesh: bool) -> List["peer_hosts.PeerRow"]:
    if include_mesh and capabilities.mesh_on():
        return list(peers)
    return [p for p in peers if p.back_kind != peer_hosts.MESH_BACK_KIND]


def read_peers(open_db: Callable[[], sqlite3.Connection], include_mesh: bool = False) -> List["peer_hosts.PeerRow"]:
    global _PEERS_CACHE
    with _PEERS_LOCK:
        cached = _PEERS_CACHE
        if cached is not None and cached[0] is open_db:
            sig = _db_signature(cached[1])
            if sig is not None and sig == cached[2]:
                return _visible(cached[3], include_mesh)
    with closing(open_db()) as conn:
        row = conn.execute("PRAGMA database_list").fetchone()
        path = row[2] if row and len(row) > 2 else ""
        sig = _db_signature(path) if path else None
        peers = peer_hosts.list_peers(conn, include_mesh=True)
    with _PEERS_LOCK:
        _PEERS_CACHE = (open_db, path, sig, peers) if sig is not None else None
    return _visible(peers, include_mesh)


async def _cold(open_db: Callable[[], sqlite3.Connection], peer: "peer_hosts.PeerRow") -> List[SessionInfo]:
    try:
        return await asyncio.to_thread(_cold_rows, open_db, peer)
    except (sqlite3.Error, OSError) as exc:
        logger.info("peer_cold_rows_unreadable", peer=peer.key, reason=type(exc).__name__)
        return []


async def for_caller(
    infos: List[SessionInfo],
    *,
    is_peer: bool,
    open_db: Callable[[], sqlite3.Connection],
    links: Optional["peer_links.PeerLinks"] = None,
    include_swarm: bool = False,
    include_relayed: bool = False,
    caller_install_id: Optional[str] = None,
) -> List[SessionInfo]:
    if is_peer:
        if include_swarm or caller_install_id is not None:
            owned = await asyncio.to_thread(
                peer_serve.serve_to_peer,
                infos,
                open_db,
                include_swarm=include_swarm,
                caller_install_id=caller_install_id,
            )
        else:
            owned = await asyncio.to_thread(peer_serve.serve_to_peer, infos, open_db)
        if include_relayed:
            relayed = await asyncio.to_thread(
                relayed_for_peer,
                open_db,
                links,
                caller_install_id=caller_install_id,
                include_swarm=include_swarm,
            )
            return owned + relayed
        return owned
    return infos + await peer_rows(open_db, links)


from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from src.api import projects_service
from src.config import settings
from src.core.pack.identity import home, replicas
from src.core.pack.move import turn
from src.core.pack.send import follow
from src.cplugs.sdk import turn_events

logger = structlog.get_logger()

_COPY = "json_extract(m.detail_json, '$.mode') = 'copy' AND m.state = 'moved'"
_inflight: Set[Tuple[str, str]] = set()
_again: Set[Tuple[str, str]] = set()
_tasks: Set["asyncio.Task[None]"] = set()
_unsubscribe: Optional[Any] = None


def peers_of(conn: Any, session_uuid: str) -> List[str]:
    rows = conn.execute(
        f"SELECT m.target_install_id AS peer FROM pack_session_moves m JOIN sessions s ON s.session_uuid = m.session_uuid "
        f"WHERE m.role = 'source' AND m.session_uuid = ? AND s.archived_at IS NULL AND {_COPY} "
        f"UNION SELECT m.source_install_id FROM pack_session_moves m JOIN sessions s ON s.session_uuid = m.session_uuid "
        f"WHERE m.role = 'target' AND m.session_uuid = ? AND s.archived_at IS NULL AND {_COPY}", (session_uuid, session_uuid)).fetchall()
    return [r[0] for r in rows]


def paired_in(conn: Any, peer_install_id: str, project_id: int) -> List[str]:
    rows = conn.execute(
        f"SELECT DISTINCT m.session_uuid FROM pack_session_moves m JOIN sessions s ON s.session_uuid = m.session_uuid "
        f"WHERE s.archived_at IS NULL AND s.project_id = ? AND {_COPY} "
        f"AND ((m.role = 'source' AND m.target_install_id = ?) OR (m.role = 'target' AND m.source_install_id = ?))",
        (project_id, peer_install_id, peer_install_id)).fetchall()
    return [r[0] for r in rows]


def _counterpart(conn: Any, project: Dict[str, Any], peer: str) -> bool:
    if project["pack_state"] == home.MOVED_AWAY:
        return False
    if project["pack_state"] == home.HOME:
        return peer in {r["install_id"] for r in replicas.list_replicas(conn, project["uid"])}
    return project.get("home_install_id") == peer


async def _busy(app_state: Any, uuids: List[str]) -> bool:
    from src.core.session_delivery import bring_up  # noqa: PLC0415

    ops = bring_up.ops_for_app(app_state)
    for uuid in uuids:
        if not turn.at_turn_end(await bring_up.find_live(ops, uuid)):
            return True
    return False


async def _follow(app_state: Any, project: Dict[str, Any], peer: str, uuids: List[str]) -> None:
    busy = await _busy(app_state, uuids)
    await asyncio.to_thread(follow.fast_forward, project["root"], peer, busy=busy, air_gap=bool(project.get("air_gap")))


async def _send(project_uid: str, peer: str) -> None:
    from src.api import project_transport_routes as transport  # noqa: PLC0415

    key = (project_uid, peer)
    if key in _inflight:
        _again.add(key)
        return
    _inflight.add(key)
    try:
        while True:
            _again.discard(key)

            def read() -> Optional[Dict[str, Any]]:
                with closing(projects_service.open_db_or_503(settings)) as conn:
                    row = conn.execute("SELECT * FROM projects WHERE uid = ?", (project_uid,)).fetchone()
                    return dict(row) if row is not None and _counterpart(conn, dict(row), peer) else None

            project = await asyncio.to_thread(read)
            if project is None:
                return
            result = await transport.carry_to(project, peer, peer, False)
            logger.info("pack_copy_sync_sent", project_uid=project_uid, sent=result.get("sent"), error=result.get("error"), reason=result.get("reason"))
            if key not in _again:
                return
    finally:
        _inflight.discard(key)
        _again.discard(key)


async def on_turn_end(app_state: Any, ses_id: str) -> None:
    from src.core.session_delivery import bring_up  # noqa: PLC0415

    def any_copy() -> bool:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            return conn.execute("SELECT 1 FROM pack_session_moves m WHERE " + _COPY + " LIMIT 1").fetchone() is not None

    if not await asyncio.to_thread(any_copy):
        return
    ops = bring_up.ops_for_app(app_state)
    infos = await ops.list()
    uuid = (await ops.durable_keys(infos)).get(ses_id)
    if uuid is None:
        return

    def pairs() -> List[Tuple[str, Dict[str, Any]]]:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            row = conn.execute("SELECT p.* FROM sessions s JOIN projects p ON p.id = s.project_id WHERE s.session_uuid = ?", (uuid,)).fetchone()
            if row is None:
                return []
            project = dict(row)
            return [(peer, project) for peer in peers_of(conn, uuid) if _counterpart(conn, project, peer)]

    for peer, project in await asyncio.to_thread(pairs):
        await _follow(app_state, project, peer, [uuid])
        await _send(project["uid"], peer)


async def after_apply(app_state: Any, project: Dict[str, Any], sender_install_id: str) -> None:
    try:
        def read() -> List[str]:
            with closing(projects_service.open_db_or_503(settings)) as conn:
                return paired_in(conn, sender_install_id, project["id"])

        uuids = await asyncio.to_thread(read)
        if uuids:
            await _follow(app_state, project, sender_install_id, uuids)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pack_copy_follow_failed", error=type(exc).__name__)


def subscribe(app_state: Any) -> None:
    global _unsubscribe
    unsubscribe()
    loop = asyncio.get_running_loop()

    def listener(ses_id: Optional[str]) -> None:
        if not ses_id:
            return

        def start() -> None:
            task = loop.create_task(_guarded(app_state, ses_id), name="pack-copy-sync")
            _tasks.add(task)
            task.add_done_callback(_tasks.discard)

        loop.call_soon_threadsafe(start)

    _unsubscribe = turn_events.subscribe(listener)


async def _guarded(app_state: Any, ses_id: str) -> None:
    try:
        await on_turn_end(app_state, ses_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pack_copy_sync_failed", error=type(exc).__name__)


def unsubscribe() -> None:
    global _unsubscribe
    if _unsubscribe is not None:
        _unsubscribe()
        _unsubscribe = None

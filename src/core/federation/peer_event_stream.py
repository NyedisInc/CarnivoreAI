
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from contextlib import closing
from typing import Any, Callable, Dict, Optional, Set, Tuple

import structlog
from websockets.exceptions import WebSocketException

from src.core import session_change_notice
from src.core.federation import peer_hosts, peer_links, peer_listing, peer_listing_push
from src.core.federation.peer_client import PeerClient
from src.core.federation.peer_terminal_proxy import PeerUnavailable, connect_upstream
from src.core.hosts.identity import remote_session_id
from src.core.notifications import contracts, types
from src.core.notifications.sources.toast import attention_notify_type
from src.models import WSMessageType

logger = structlog.get_logger()

LIVE: Set[str] = set()
_TASKS: Dict[str, asyncio.Task] = {}
_STARTED_WITH: Dict[str, PeerClient] = {}
MAX_BACKOFF = 30.0
_LIGHT_KEYS = ("tmux_session", "epoch", "activity_status", "unread", "startup_gate")


def translate(frame: Dict[str, Any], host_key: str) -> Optional[Dict[str, Any]]:
    kind = frame.get("type")
    try:
        if kind == WSMessageType.EVENTS_HELLO.value:
            return session_change_notice.build_structural_notice("peer")
        if kind == WSMessageType.SESSION_STATUS_CHANGED.value and frame.get("tmux_session"):
            out = session_change_notice.build_status_notice(
                session_id=remote_session_id(host_key, str(frame["tmux_session"])),
                **{k: frame[k] for k in _LIGHT_KEYS if k in frame})
            return {**out, "origin": contracts.ORIGIN_PEER}
        toast = frame.get("toast")
        if kind == WSMessageType.TOAST_NEW.value and isinstance(toast, dict) and toast.get("session_name"):
            wire = remote_session_id(host_key, str(toast["session_name"]))
            return {**frame, "origin": contracts.ORIGIN_PEER, "toast": {**toast, "session_id": wire, "origin": contracts.ORIGIN_PEER}}
    except ValueError:
        logger.info("peer_event_unaddressable", host_key=host_key)
    return None


def offer_to_engine(frame: Dict[str, Any]) -> None:
    toast = frame.get("toast")
    if not isinstance(toast, dict):
        return
    type_id = toast.get("notify_type")
    if not isinstance(type_id, str) or not types.is_registered(type_id):
        try:
            type_id = attention_notify_type(str(toast.get("kind")), None)
        except ValueError:
            return
    contracts.emit(contracts.NotifyEvent(
        type_id=type_id, kind=str(toast.get("kind")), ts=time.time(), origin=contracts.ORIGIN_PEER,
        title=str(toast.get("title") or ""), session_id=str(toast.get("session_id") or "") or None,
        details=str(toast.get("body") or "") or None))


async def _apply_listing(frame: Dict[str, Any], install_id: str, open_db: Callable[[], sqlite3.Connection]) -> None:
    peer = next((p for p in await asyncio.to_thread(peer_listing.read_peers, open_db) if p.peer_install_id == install_id), None)
    if peer is None or not await peer_listing_push.apply(frame, peer, open_db):
        raise PeerUnavailable()


async def _follow_once(app_state: Any, host_key: str, client: PeerClient, install_id: str,
                       open_db: Callable[[], sqlite3.Connection]) -> None:
    upstream = await connect_upstream(client, "/ws/events?listing=push")
    try:
        LIVE.add(host_key)
        async for raw in upstream:
            try:
                parsed = await asyncio.to_thread(json.loads, raw) if len(raw) > 65536 else json.loads(raw)
                if isinstance(parsed, dict) and parsed.get("type") == WSMessageType.PEER_LISTING.value:
                    await _apply_listing(parsed, install_id, open_db)
                    continue
                local = translate(parsed, host_key)
            except (ValueError, TypeError, AttributeError, RecursionError):
                continue
            if local is None:
                continue
            session_change_notice.publish(app_state, local)
            dispatcher = getattr(app_state, 'crosstalk_dispatcher', None)
            if dispatcher is not None and local.get('type') in (
                    WSMessageType.SESSION_STATUS_CHANGED.value, WSMessageType.SESSIONS_CHANGED.value):
                dispatcher.on_peer_change(local.get('session_id'))
            if local.get("type") == WSMessageType.TOAST_NEW.value:
                offer_to_engine(local)
    finally:
        LIVE.discard(host_key)
        peer_listing_push.drop(install_id)
        await upstream.close()


async def _follow(app_state: Any, host_key: str, client: PeerClient, install_id: str,
                  open_db: Callable[[], sqlite3.Connection]) -> None:
    failures = 0
    while True:
        try:
            await _follow_once(app_state, host_key, client, install_id, open_db)
            failures = 0
        except asyncio.CancelledError:
            raise
        except (PeerUnavailable, WebSocketException, OSError):
            failures += 1
        except Exception:  # noqa: BLE001
            failures += 1
            logger.exception("peer_event_stream_failed", host_key=host_key)
        await asyncio.sleep(min(MAX_BACKOFF, 2.0 ** min(failures, 5)))


def sync(app_state: Any, open_db: Callable[[], sqlite3.Connection]) -> None:
    links = peer_links.LINKS
    wanted: Dict[str, Tuple[str, PeerClient]] = {}
    if links is not None and links.connected_clients():
        with closing(open_db()) as conn:
            for install_id, client in links.connected_clients():
                row = peer_hosts.get(conn, install_id)
                if row is not None:
                    wanted[row.key] = (install_id, client)
    for key in [k for k in _TASKS if k not in wanted or _TASKS[k].done() or _STARTED_WITH.get(k) is not wanted[k][1]]:
        _TASKS.pop(key).cancel()
        _STARTED_WITH.pop(key, None)
        LIVE.discard(key)
    for key, (install_id, client) in wanted.items():
        if key not in _TASKS:
            _STARTED_WITH[key] = client
            _TASKS[key] = asyncio.create_task(_follow(app_state, key, client, install_id, open_db), name=f"peer-events-{key}")


async def stop() -> None:
    tasks = list(_TASKS.values())
    _TASKS.clear()
    _STARTED_WITH.clear()
    LIVE.clear()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

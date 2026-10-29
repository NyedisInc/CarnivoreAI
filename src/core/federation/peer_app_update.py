
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Any, Callable, Dict, Optional

import httpx
import structlog

from src.core.computers import direction
from src.core.federation import peer_hosts, peer_links
from src.core.federation.peer_client import PeerRefused, PeerUnreachable

logger = structlog.get_logger()

DEADLINE_SECONDS = 8.0
PATH = "/federation/app-update"
CALLS: Dict[str, tuple] = {"status": ("GET", ""), "check": ("POST", "/check"), "install": ("POST", "/install"),
                           "auto": ("PUT", "/auto-update")}
FIELDS = ("attached", "state", "current_version", "latest_version", "percent", "detail", "checked_at", "auto_update")
NO_ROUTE = (404, 405)


def _shown(data: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict) or not isinstance(data.get("state"), str):
        return None
    return {key: data.get(key) for key in FIELDS}


def _refusal_code(reply: Any) -> str:
    try:
        detail = reply.json().get("detail")
    except (ValueError, AttributeError, RecursionError):
        return ""
    return detail.get("code", "") if isinstance(detail, dict) and isinstance(detail.get("code"), str) else ""


async def call(open_db: Callable[[], sqlite3.Connection], host_key: str, action: str, enabled: Optional[bool] = None,
               links: Optional["peer_links.PeerLinks"] = None) -> Dict[str, Any]:
    if action not in CALLS or (action == "auto") != (enabled is not None):
        return {"status": "unavailable", "reason": "bad_request"}
    links = links if links is not None else peer_links.LINKS
    if links is None:
        return {"status": "unavailable", "reason": "not_paired"}
    try:
        def find() -> Optional[peer_hosts.PeerRow]:
            with closing(open_db()) as conn:
                return next((p for p in peer_hosts.list_peers(conn) if p.key == host_key), None)
        peer = await asyncio.to_thread(find)
    except (sqlite3.Error, OSError) as exc:
        logger.info("peer_app_update_peers_unreadable", reason=type(exc).__name__)
        return {"status": "unavailable", "reason": "unreadable"}
    if peer is None:
        return {"status": "unavailable", "reason": "not_paired"}
    if direction.is_one_way_toward(peer.peer_install_id):
        return {"status": "unavailable", "reason": "one_way"}
    client = links.client(peer.peer_install_id)
    if client is None:
        return {"status": "unavailable", "reason": "disconnected"}
    method, suffix = CALLS[action]
    try:
        reply = await asyncio.wait_for(client.request(method, PATH + suffix, json={"enabled": enabled} if action == "auto" else None),
                                       DEADLINE_SECONDS)
    except asyncio.TimeoutError:
        return {"status": "unavailable", "reason": "timeout"}
    except PeerUnreachable:
        return {"status": "unavailable", "reason": "unreachable"}
    except PeerRefused as exc:
        return {"status": "unavailable", "reason": exc.code}
    except (httpx.HTTPError, ValueError, RecursionError):
        return {"status": "unavailable", "reason": "bad_answer"}
    if reply.status_code in NO_ROUTE:
        return {"status": "unsupported"}
    if reply.status_code != 200:
        return {"status": "refused", "reason": _refusal_code(reply) or f"http_{reply.status_code}"}
    try:
        shown = _shown(reply.json())
    except (ValueError, RecursionError):
        shown = None
    return {"status": "ok", "update": shown} if shown else {"status": "unavailable", "reason": "bad_answer"}


from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Dict, List, Tuple

import structlog

from src.core.federation import peer_forward
from src.core.federation.peer_client import PeerRefused, PeerUnreachable

logger = structlog.get_logger(__name__)


def peer_members(conn: sqlite3.Connection, layout_uuid: str) -> List[Tuple[str, str]]:
    rows = conn.execute(
        "SELECT ps.host_key, ps.peer_name FROM layout_members m JOIN layouts l ON l.id = m.layout_id "
        "JOIN peer_sessions ps ON ps.session_id = m.session_row_id WHERE l.layout_uuid = ?", (layout_uuid,)).fetchall()
    return [(r[0], r[1]) for r in rows]


async def forward_lease(layout_uuid: str, open_db, links) -> Dict[str, str]:
    def read():
        with closing(open_db()) as conn:
            return [(name, peer_forward._peer_by_key(conn, key), key) for key, name in peer_members(conn, layout_uuid)]

    result: Dict[str, str] = {}
    try:
        targets = await asyncio.to_thread(read)
    except (sqlite3.Error, TypeError, OSError) as exc:
        logger.warning("peer_layout_lease_read_failed", error=str(exc)[:200])
        return result
    rule = peer_forward.rule_for("PUT", "/api/v1/sessions/x/active")
    for name, peer, key in targets:
        wire = f"remote:{key}:{name}"
        client = links.client(peer.peer_install_id) if links is not None and peer is not None else None
        if client is None:
            result[wire] = "peer_unreachable"
            continue
        try:
            path, body = peer_forward.build_request(rule, name, {"session_name": wire}, [], None)
            answer = await peer_forward.send(client, rule, path, body)
            result[wire] = "ok" if answer.status_code == 200 else f"http_{answer.status_code}"
        except (PeerUnreachable, PeerRefused) as exc:
            result[wire] = "peer_unreachable"
            logger.info("peer_layout_lease_unreachable", peer=key, error=str(exc)[:120])
    return result

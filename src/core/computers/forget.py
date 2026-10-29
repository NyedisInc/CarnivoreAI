
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import structlog

from src.core import setup_state
from src.core.computers import commit, store
from src.core.federation import grants, peer_hosts, peer_listing, peer_sockets, shadow_rows
from src.core.federation.peer_client import PeerRefused, PeerUnreachable

log = structlog.get_logger(__name__)

COURTESY_TIMEOUT_S = 8.0
TOPICS = ("computers", "pack_machines", "pack_relay_offer")


async def tell_peer(links: Any, iid: str) -> bool:
    client = links.client(iid)
    if client is None:
        return False
    try:
        reply = await asyncio.wait_for(client.request("DELETE", "/federation/grants/self", timeout=COURTESY_TIMEOUT_S), COURTESY_TIMEOUT_S + 2)
    except PeerUnreachable:
        return True
    except (PeerRefused, asyncio.TimeoutError):
        return False
    return reply.status_code < 300


def _drop_rows(open_db: Callable[[], sqlite3.Connection], iid: str) -> tuple:
    with closing(open_db()) as conn:
        row = store.get(conn, iid)
        grant = grants.live_for_peer(conn, iid)
        if grant is not None:
            grants.revoke(conn, grant.grant_id)
        host = peer_hosts.get(conn, iid)
        if host is not None:
            shadow_rows.remove_peer(conn, host.key)
            peer_hosts.delete(conn, iid)
        store.delete(conn, iid)
    return (grant.grant_id if grant is not None else None), row


def _leave_local(config_path: Path, fed_dir: Path, own_iid: str, pack: commit.PackSettingsPort) -> None:
    tombstone = setup_state.pack_left_path(config_path)
    tombstone.touch(mode=0o600, exist_ok=True)
    setup_state.joined_marker_path(config_path).unlink(missing_ok=True)
    (config_path.parent / setup_state.PAIRED_SENTINEL_NAME).unlink(missing_ok=True)
    for path in fed_dir.glob("link-" + own_iid[:12] + "-*"):
        path.unlink(missing_ok=True)
    pack.mint({"master_install_id": own_iid})


async def forget_computer(iid: str, *, notify_peer: bool, open_db: Callable[[], sqlite3.Connection], links: Any,
                          pack: commit.PackSettingsPort, own_iid: str, config_path: Path, fed_dir: Path,
                          repin: Callable[[], Awaitable[Any]], notify: Optional[Callable[[str], None]] = None) -> bool:
    told = await tell_peer(links, iid) if notify_peer else False
    grant_id, row = await asyncio.to_thread(_drop_rows, open_db, iid)
    peer_listing.forget(iid)
    await links.remove(iid)
    if grant_id is not None:
        await peer_sockets.close_grant(grant_id)
    if row is not None and row.role == "main" and row.transport == "tls":
        await asyncio.to_thread(_leave_local, config_path, fed_dir, own_iid, pack)
    await repin()
    if notify is not None:
        for topic in TOPICS:
            notify(topic)
    log.info("computer_forgotten", iid=iid[:8], role=row.role if row is not None else None, peer_told=told)
    return told

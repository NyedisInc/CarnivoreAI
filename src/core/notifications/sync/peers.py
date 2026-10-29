
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

import structlog

from src.core.federation import grants, peer_hosts, peer_links
from src.core.federation.peer_client import PeerRefused, PeerUnreachable

log = structlog.get_logger(__name__)

MIN_MINOR = 1
REQUEST_TIMEOUT_SECONDS = 20.0


class PeerCallError(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PeerInfo:

    key: str
    label: str
    install_id: str
    connected: bool
    minor: int

    @property
    def speaks_sync(self) -> bool:
        return self.minor >= MIN_MINOR


class PeerGateway(Protocol):

    async def roster(self) -> List[PeerInfo]: ...

    async def post(self, install_id: str, path: str, body: Dict[str, Any]) -> Tuple[int, Any]: ...

    async def set_scope(self, install_id: str, granted: bool) -> None: ...


class LinkGateway:

    def __init__(self, open_db: Callable[[], sqlite3.Connection],
                 links: Callable[[], Optional[peer_links.PeerLinks]]) -> None:
        self._open_db, self._links = open_db, links

    async def roster(self) -> List[PeerInfo]:
        links = self._links()

        def read() -> List[peer_hosts.PeerRow]:
            with closing(self._open_db()) as conn:
                return peer_hosts.list_peers(conn)

        try:
            rows = await asyncio.to_thread(read)
        except (sqlite3.Error, OSError) as exc:
            log.info("notification_sync_roster_unreadable", reason=type(exc).__name__)
            return []
        return [PeerInfo(r.key, r.label, r.peer_install_id,
                         links is not None and links.state(r.peer_install_id) == "connected",
                         links.minor(r.peer_install_id) if links is not None else 0) for r in rows]

    async def post(self, install_id: str, path: str, body: Dict[str, Any]) -> Tuple[int, Any]:
        links = self._links()
        client = links.client(install_id) if links is not None else None
        if client is None:
            raise PeerCallError("unreachable")
        try:
            reply = await asyncio.wait_for(client.request("POST", path, json=body), REQUEST_TIMEOUT_SECONDS)
        except (PeerUnreachable, asyncio.TimeoutError):
            raise PeerCallError("unreachable") from None
        except PeerRefused:
            raise PeerCallError("refused") from None
        try:
            return reply.status_code, (reply.json() if reply.status_code == 200 else None)
        except ValueError:
            raise PeerCallError("bad_answer") from None

    async def set_scope(self, install_id: str, granted: bool) -> None:
        def write() -> None:
            with closing(self._open_db()) as conn:
                grant = grants.live_for_peer(conn, install_id)
                if grant is None:
                    return
                scopes = set(grant.scopes)
                scopes = scopes | {grants.SCOPE_SETTINGS} if granted else scopes - {grants.SCOPE_SETTINGS}
                if scopes:
                    grants.set_scopes(conn, grant.grant_id, tuple(scopes))

        try:
            await asyncio.to_thread(write)
        except (sqlite3.Error, OSError, grants.GrantError) as exc:
            log.warning("notification_sync_scope_failed", reason=type(exc).__name__)

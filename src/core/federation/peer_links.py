
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Awaitable, Callable, Dict, Optional, Tuple

import structlog

from src.core.db import get_meta
from src.core.db_models import META_INSTALL_ID
from src.core.federation import fed_key, grants, peer_hosts
from src.core.federation.grants import Grant
from src.core.federation.peer_hosts import PeerRow
from src.core.federation.peer_client import PeerClient, Route
from src.core.federation.peer_dial import InitiatorTransport
from src.core.federation.peer_link import CONNECTED, DISCONNECTED, LinkDown, PeerLink
from src.core.federation.transport import Transport
from src.core.hosts.ssh_exec import SshArgumentError, SshDestination
from src.core.hosts.ssh_master import SshTransportError, backoff_delay

logger = structlog.get_logger()


class PeerLinks:

    def __init__(self, *, open_db: Callable[[], sqlite3.Connection], listener_path: str) -> None:
        self._open_db, self._listener = open_db, listener_path
        self._links: Dict[str, PeerLink] = {}
        self._transports: Dict[str, Transport] = {}
        self._back: Dict[str, Tuple[str, object, str]] = {}
        self._route_events: Dict[str, asyncio.Event] = {}
        self._key: Optional["fed_key.DeviceKey"] = None
        self._pins: Dict[str, Optional[str]] = {}
        self._up: set = set()
        self._connect_listeners: list = []
        self._beat_hook: Optional[Callable[[str, PeerClient, list], Awaitable[None]]] = None
        self.transport_factory: Optional[Callable[[PeerRow, Callable[[Route], PeerClient]], Optional[Transport]]] = None

    def add_connect_listener(self, listener: Callable[[str], None]) -> None:
        self._connect_listeners.append(listener)

    def set_beat_hook(self, hook: Callable[[str, PeerClient, list], Awaitable[None]]) -> None:
        self._beat_hook = hook

    def _on_beat_for(self, peer_install_id: str):
        async def on_beat(client: PeerClient) -> None:
            link, hook = self._links.get(peer_install_id), self._beat_hook
            if hook is not None and link is not None:
                await hook(peer_install_id, client, link.capabilities)
        return on_beat

    def capabilities(self, peer_install_id: str) -> list:
        link = self._links.get(peer_install_id)
        return list(link.capabilities) if link is not None else []

    def _note_state(self, install_id: str, state: str) -> None:
        if state != CONNECTED:
            self._up.discard(install_id)
            return
        if install_id in self._up:
            return
        self._up.add(install_id)
        for listener in list(self._connect_listeners):
            try:
                listener(install_id)
            except Exception:  # noqa: BLE001
                logger.exception("peer_link_connect_listener_failed")

    async def _signer(self) -> "fed_key.DeviceKey":
        if self._key is None:
            def load():
                with closing(self._open_db()) as conn:
                    iid = get_meta(conn, META_INSTALL_ID)
                return fed_key.load_key(iid or "")
            self._key = await asyncio.to_thread(load)
        return self._key

    def _write_state(self, install_id: str, state: str, protocol: Optional[int]) -> None:
        with closing(self._open_db()) as conn:
            peer_hosts.set_state(conn, install_id, state, protocol)

    def _persist_state(self, install_id: str) -> Callable[[str, Optional[int]], None]:
        def write(state: str, protocol: Optional[int]) -> None:
            self._note_state(install_id, state)
            asyncio.get_running_loop().run_in_executor(None, self._write_state, install_id, state, protocol)
        return write

    async def _client_factory(self, grant_id: str, peer_install_id: str,
                              peer_public_key: Optional[str] = None) -> Callable[[Route], PeerClient]:
        await self._signer()
        self._pins[peer_install_id] = peer_public_key
        return lambda route: PeerClient(route, grant_id=grant_id, peer_install_id=peer_install_id,
                                        sign=lambda message: self._key.sign(message),  # type: ignore[union-attr]
                                        peer_public_key=self._pins.get(peer_install_id))

    def use_key(self, key: "fed_key.DeviceKey") -> None:
        self._key = key

    def pin_peer_key(self, peer_install_id: str, public_key: str) -> None:
        if self._pins.get(peer_install_id) is not None:
            self._pins[peer_install_id] = public_key

    def connected_clients(self) -> "list[tuple[str, PeerClient]]":
        return [(peer, link.client) for peer, link in self._links.items()
                if link.state == CONNECTED and link.client is not None]

    async def start_initiator(self, row: "peer_hosts.PeerRow", transport: Optional[Transport] = None,
                              ) -> None:
        await self.remove(row.peer_install_id)
        def pinned() -> Optional[str]:
            with closing(self._open_db()) as conn:
                grant = grants.live_for_peer(conn, row.peer_install_id)
            return grant.public_key if grant is not None else None

        pin = await asyncio.to_thread(pinned)
        if pin is None:
            logger.warning("peer_link_not_started_no_grant", peer=row.peer_install_id[:8])
            await asyncio.to_thread(self._write_state, row.peer_install_id, "unpaired", None)
            return
        make = await self._client_factory(row.peer_grant_id, row.peer_install_id, pin)
        try:
            transport = transport or (self.transport_factory and self.transport_factory(row, make)) or InitiatorTransport(
                host_key=row.key, dest=SshDestination(row.ssh_target, row.ssh_port), remote_port=row.peer_port or 8000,
                listener_path=self._listener, make_client=make, peer_grant_id=row.peer_grant_id,
                back_kind=row.back_kind)
        except (SshArgumentError, SshTransportError) as exc:
            logger.warning("peer_link_not_started_socket", peer=row.peer_install_id[:8], error=str(exc)[:200])
            await asyncio.to_thread(self._write_state, row.peer_install_id, "disconnected", None)
            return
        waits = {"settle": transport.settle, "delay": lambda _attempt: 0.5} if transport.settle is not None else {}
        link = PeerLink(peer_install_id=row.peer_install_id, establish=transport.establish, make_client=make,
                        on_state=self._persist_state(row.peer_install_id), renew=transport.renew,
                        on_beat=self._on_beat_for(row.peer_install_id), **waits)
        self._links[row.peer_install_id], self._transports[row.peer_install_id] = link, transport
        link.start()

    async def accept_route(self, grant: Grant, route: Tuple[str, object, str]) -> None:
        peer = grant.peer_install_id
        link, previous = self._links.get(peer), self._back.get(peer)
        if link is not None and previous is not None and previous != route:
            await link.stop()
            self._back[peer] = route
            self._route_events.setdefault(peer, asyncio.Event()).set()
            link.start()
            return
        self._back[peer] = route
        self._route_events.setdefault(peer, asyncio.Event()).set()
        if link is not None or not grant.remote_grant_id:
            return
        def upsert() -> None:
            with closing(self._open_db()) as conn:
                peer_hosts.upsert(conn, install_id=peer, label=grant.label, grant_id=grant.remote_grant_id or "",
                                  fid=grant.fid, initiator=False)
        await asyncio.to_thread(upsert)
        make = await self._client_factory(grant.remote_grant_id, peer, grant.public_key)

        def on_state(state: str, protocol: Optional[int]) -> None:
            if state == DISCONNECTED:
                self._back.pop(peer, None)
            self._persist_state(peer)(state, protocol)

        async def establish() -> Route:
            current = self._back.get(peer)
            if current is None:
                raise LinkDown("no route back from the peer yet")
            return Route(*current)

        async def wait_for_route() -> None:
            while peer not in self._back:
                event = self._route_events.setdefault(peer, asyncio.Event())
                event.clear()
                if peer not in self._back:
                    await event.wait()

        link = PeerLink(peer_install_id=peer, establish=establish, make_client=make, on_state=on_state,
                        delay=backoff_delay, settle=wait_for_route)
        self._links[peer] = link
        link.start()

    async def boot(self) -> None:
        try:
            def rows():
                with closing(self._open_db()) as conn:
                    return [r for r in peer_hosts.list_peers(conn) if r.initiator]
            for row in await asyncio.to_thread(rows):
                await self.start_initiator(row)
        except Exception:  # noqa: BLE001
            logger.exception("peer_links_boot_failed")

    async def remove(self, peer_install_id: str) -> None:
        link = self._links.pop(peer_install_id, None)
        transport = self._transports.pop(peer_install_id, None)
        self._back.pop(peer_install_id, None)
        self._route_events.pop(peer_install_id, None)
        if link is not None:
            await link.stop()
        if transport is not None:
            await transport.close()

    def client(self, peer_install_id: str) -> Optional[PeerClient]:
        link = self._links.get(peer_install_id)
        return link.live_client() if link is not None else None

    def minor(self, peer_install_id: str) -> int:
        link = self._links.get(peer_install_id)
        return link.minor if link is not None else 0

    def state(self, peer_install_id: str) -> str:
        link = self._links.get(peer_install_id)
        return link.state if link is not None else DISCONNECTED

    async def shutdown(self) -> None:
        for peer in list(self._links):
            await self.remove(peer)


LINKS: Optional[PeerLinks] = None

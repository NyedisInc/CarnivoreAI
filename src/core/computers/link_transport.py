
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

from src.core.computers import store
from src.core.computers.link_listener import failure_fields
from src.core.computers.link_streams import LocalSocket, inbound_handler
from src.core.computers.member_listener import Rendezvous
from src.core.computers.mux import frames as f
from src.core.computers.mux.session import MuxError, MuxSession
from src.core.federation.pairing import PROTOCOL_MAJOR
from src.core.federation.peer_client import PeerClient, PeerRefused, Route
from src.core.federation.peer_dial import socket_dir_for
from src.core.federation.peer_hosts import PeerRow
from src.core.federation.peer_link import LinkDown
from src.core.federation.transport import Transport
from src.core.hosts.ssh_exec import validate_control_path
from src.core.hosts.ssh_master import ensure_control_dir

log = structlog.get_logger(__name__)

HELLO_TIMEOUT = 5.0


def _back_path(hello: Dict[str, Any]) -> str:
    path = hello.get("back_path")
    if not isinstance(path, str) or not path or len(path) > 1024 or not path.isprintable():
        raise LinkDown("main sent no usable back path")
    return path


class TlsInitiatorTransport:

    def __init__(self, *, install_id: str, host_key: str, rendezvous: Rendezvous,
                 get_link: Callable[[], Optional[store.LinkRow]], listener_path: str,
                 make_client: Callable[[Route], PeerClient],
                 addresses: Callable[[], List[str]] = lambda: [],
                 listen_port: Callable[[], Optional[int]] = lambda: None,
                 on_first_link: Optional[Callable[[], Awaitable[None]]] = None,
                 on_rotated: Optional[Callable[[str], Awaitable[None]]] = None,
                 control_dir: Optional[Path] = None) -> None:
        self._rv, self._get_link, self._listener = rendezvous, get_link, listener_path
        self._make_client, self._on_first_link, self._on_rotated = make_client, on_first_link, on_rotated
        self._addresses, self._listen_port = addresses, listen_port
        directory = ensure_control_dir(socket_dir_for(control_dir or Path.home() / ".carnivore" / "cm"))
        stem = hashlib.sha256(f"{install_id}:{host_key}:tls".encode()).hexdigest()[:10]
        self.out_path = validate_control_path(f"{directory}/{stem}-t")
        self._body: Optional[dict] = None
        self._session: Optional[MuxSession] = None
        self._local: Optional[LocalSocket] = None
        self._linked = False

    async def settle(self) -> None:
        await self._rv.settle()

    async def establish(self) -> Route:
        await self._teardown(f.GO_NORMAL)
        link = self._get_link()
        if link is None or link.cert_der is None:
            raise LinkDown("no link to main on record")
        conn = self._rv.take()
        if conn is None:
            raise LinkDown("waiting for main")
        reader, writer = conn
        session = MuxSession(reader, writer, dialer=True, on_open=inbound_handler(self._listener))
        self._session = session
        try:
            await self._hello(session)
            await self._note_rotation(writer, link)
            self._local = LocalSocket(session, self.out_path)
            await self._local.start()
            await self.renew(self._make_client(Route("unix", self.out_path)))
            if not self._linked and self._on_first_link is not None:
                await self._on_first_link()
            self._linked = True
        except BaseException:
            await self._teardown(f.GO_NORMAL)
            raise
        return Route("unix", self.out_path)

    async def _note_rotation(self, writer: asyncio.StreamWriter, link: store.LinkRow) -> None:
        ssl_obj = writer.get_extra_info("ssl_object")
        der = ssl_obj.getpeercert(binary_form=True) if ssl_obj is not None else None
        sha = hashlib.sha256(der).hexdigest() if der else None
        if sha is None or self._on_rotated is None or link.next_cert_sha256 != sha:
            return
        try:
            await self._on_rotated(sha)
        except Exception as exc:  # noqa: BLE001
            log.error("link_on_rotated_failed", **failure_fields(exc))

    async def _hello(self, session: MuxSession) -> None:
        await session.start({"v": f.PROTOCOL_VERSION, "proto": PROTOCOL_MAJOR, "addresses": list(self._addresses()),
                             "listen_port": self._listen_port()})
        try:
            hello = await asyncio.wait_for(session.hello(), HELLO_TIMEOUT)
        except asyncio.TimeoutError:
            raise LinkDown("main did not answer the link hello") from None
        except MuxError:
            reasons = {f.GO_VERSION: "main speaks another link version", f.GO_REMOVED: "main removed this computer"}
            raise LinkDown(reasons.get(session.goaway_reason, "main closed the link during hello")) from None
        self._body = {"kind": "unix", "path": _back_path(hello)}

    async def renew(self, client: PeerClient) -> None:
        response = await client.request("POST", "/federation/link", json=self._body)
        if response.status_code != 200:
            raise PeerRefused(f"http_{response.status_code}")

    async def _teardown(self, reason: int) -> None:
        session, local, self._session, self._local = self._session, self._local, None, None
        if session is not None:
            await session.close(reason)
        if local is not None:
            await local.close()

    async def close(self) -> None:
        await self._teardown(f.GO_NORMAL)


def tls_transport_factory(*, install_id: str, listener_path: str, rendezvous: Rendezvous,
                          on_first_link: Callable[[str], Awaitable[None]],
                          addresses: Callable[[], List[str]], listen_port: Callable[[], Optional[int]],
                          cache: Optional[store.LinkCache] = None,
                          on_rotated: Optional[Callable[[str, str], Awaitable[None]]] = None,
                          control_dir: Optional[Path] = None) -> Callable[[PeerRow, Callable[[Route], PeerClient]], Optional[Transport]]:
    rows = cache if cache is not None else store.CACHE

    def factory(row: PeerRow, make: Callable[[Route], PeerClient]) -> Optional[Transport]:
        peer = row.peer_install_id
        if rows.tls_main_for(peer) is None:
            return None

        async def first() -> None:
            await on_first_link(peer)

        async def rotated(sha: str) -> None:
            if on_rotated is not None:
                await on_rotated(peer, sha)

        return TlsInitiatorTransport(
            install_id=install_id, host_key=row.key, rendezvous=rendezvous, get_link=lambda: rows.tls_main_for(peer),
            listener_path=listener_path, make_client=make, addresses=addresses, listen_port=listen_port,
            on_first_link=first, on_rotated=rotated, control_dir=control_dir)
    return factory

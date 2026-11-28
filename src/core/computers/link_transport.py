
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
        raise LinkDown("alpha sent no usable back path")
    return path


class TlsInitiatorTransport:

    def __init__(self, *, install_id: str, host_key: str, rendezvous: Rendezvous,
                 get_link: Callable[[], Optional[store.LinkRow]], listener_path: str,
                 make_client: Callable[[Route], PeerClient],
                 addresses: Callable[[], List[str]] = lambda: [],
                 listen_port: Callable[[], Optional[int]] = lambda: None,
                 on_first_link: Optional[Callable[[], Awaitable[None]]] = None,
                 on_rotated: Optional[Callable[[str], Awaitable[None]]] = None,
                 hello_extras: Callable[[], Dict[str, Any]] = lambda: {},
                 on_relay_id: Optional[Callable[[str], None]] = None,
                 on_roster: Optional[Callable[[Any], Awaitable[None]]] = None,
                 control_dir: Optional[Path] = None) -> None:
        self._hello_extras, self._on_relay_id, self._on_roster = hello_extras, on_relay_id, on_roster
        self._watch: Optional["asyncio.Task[None]"] = None
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
        self._announced = False

    async def reannounce(self) -> bool:
        if self._session is None or self._announced or not self._hello_extras():
            return False
        self._announced = True
        await self._teardown(f.GO_NORMAL)
        return True

    async def settle(self) -> None:
        await self._rv.settle()

    async def establish(self) -> Route:
        await self._teardown(f.GO_NORMAL)
        link = self._get_link()
        if link is None or link.cert_der is None:
            raise LinkDown("no link to alpha on record")
        conn = self._rv.take()
        if conn is None:
            raise LinkDown("waiting for alpha")
        reader, writer = conn
        relayed = self._rv.taken_via_relay
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
            if relayed:
                self._watch = asyncio.get_running_loop().create_task(self._leave_relay_for_direct(session), name="link-relay-watch")
        except BaseException:
            await self._teardown(f.GO_NORMAL)
            raise
        return Route("unix", self.out_path)

    async def _leave_relay_for_direct(self, session: MuxSession) -> None:
        await self._rv.settle()
        log.info("link_direct_available_leaving_relay")
        await session.close(f.GO_NORMAL)

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
        extras = self._hello_extras()
        self._announced = bool(extras)
        await session.start({"v": f.PROTOCOL_VERSION, "proto": PROTOCOL_MAJOR, "addresses": list(self._addresses()),
                             "listen_port": self._listen_port(), **extras})
        try:
            hello = await asyncio.wait_for(session.hello(), HELLO_TIMEOUT)
        except asyncio.TimeoutError:
            raise LinkDown("alpha did not answer the link hello") from None
        except MuxError:
            reasons = {f.GO_VERSION: "alpha speaks another link version", f.GO_REMOVED: "alpha removed this computer"}
            raise LinkDown(reasons.get(session.goaway_reason, "alpha closed the link during hello")) from None
        self._body = {"kind": "unix", "path": _back_path(hello)}
        relay_id = hello.get("relay_id")
        if self._on_relay_id is not None and isinstance(relay_id, str):
            self._on_relay_id(relay_id)
        if self._on_roster is not None and hello.get("roster") is not None:
            try:
                await self._on_roster(hello["roster"])
            except Exception as exc:  # noqa: BLE001
                log.error("link_roster_failed", **failure_fields(exc))

    async def renew(self, client: PeerClient) -> None:
        response = await client.request("POST", "/federation/link", json=self._body)
        if response.status_code != 200:
            raise PeerRefused(f"http_{response.status_code}")

    async def _teardown(self, reason: int) -> None:
        session, local, self._session, self._local = self._session, self._local, None, None
        watch, self._watch = self._watch, None
        if watch is not None and watch is not asyncio.current_task():
            watch.cancel()
            await asyncio.gather(watch, return_exceptions=True)
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
                          hello_extras: Callable[[str], Dict[str, Any]] = lambda _peer: {},
                          on_relay_id: Optional[Callable[[str, str], None]] = None,
                          on_roster: Optional[Callable[[str, Any], Awaitable[None]]] = None,
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
            on_first_link=first, on_rotated=rotated, hello_extras=lambda: hello_extras(peer),
            on_relay_id=lambda relay_id: on_relay_id(peer, relay_id) if on_relay_id is not None else None,
            on_roster=(lambda raw: on_roster(peer, raw)) if on_roster is not None else None, control_dir=control_dir)
    return factory

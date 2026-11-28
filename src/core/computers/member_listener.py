
from __future__ import annotations

import asyncio
import hashlib
import socket
import ssl
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence, Tuple

import structlog

from src.core.computers.link_listener import DEFAULT_LINK_PORT, AlertingSSLObject, _HandshakeGate, _TlsGate
from src.core.computers.mux import frames as mf
from src.core.computers.mux.session import MuxError, MuxSession
from src.core.computers.tls_identity import LinkCert, LinkIdentity, server_link_ctx
from src.core.computers.mesh_link import MESH_ALPN
from src.core.federation.pairing import PROTOCOL_MAJOR
from src.core.pack.machines import capabilities

log = structlog.get_logger(__name__)

PER_SOURCE_HANDSHAKES = 2
TOTAL_HANDSHAKES = 8
MESH_PER_SOURCE = 4
MESH_TOTAL = 32
HOLD_SECONDS = 10.0
MEMBER_HANDSHAKE_TIMEOUT = 2.0
RESERVE_SPAN = range(2, 12)

STOPPED, LISTENING, PORT_BUSY = "stopped", "listening", "port_busy"

Conn = Tuple[asyncio.StreamReader, asyncio.StreamWriter]


class Rendezvous:

    def __init__(self, hold: float = HOLD_SECONDS) -> None:
        self._hold = hold
        self._slot: Optional[Conn] = None
        self._timer: Optional[asyncio.TimerHandle] = None
        self._ready = asyncio.Event()
        self._slot_relay = False
        self.taken_via_relay = False
        self.taken_local_address: Optional[str] = None

    def offer(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, via_relay: bool = False) -> None:
        self._drop()
        self._slot, self._slot_relay = (reader, writer), via_relay
        self._ready.set()
        self._timer = asyncio.get_running_loop().call_later(self._hold, self._expire, writer)

    def _expire(self, writer: asyncio.StreamWriter) -> None:
        if self._slot is not None and self._slot[1] is writer:
            log.info("member_listener_offer_expired")
            self._drop()

    def _drop(self) -> None:
        slot, self._slot = self._slot, None
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._ready.clear()
        if slot is not None:
            slot[1].close()

    def take(self) -> Optional[Conn]:
        slot, self._slot = self._slot, None
        self.taken_via_relay = slot is not None and self._slot_relay
        sock = slot[1].get_extra_info("sockname") if slot is not None else None
        self.taken_local_address = sock[0] if isinstance(sock, (tuple, list)) and sock else None
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._ready.clear()
        return slot

    async def settle(self) -> None:
        while self._slot is None:
            await self._ready.wait()

    def close(self) -> None:
        self._drop()


def reserve_listen_port(base: int, free: Callable[[int], bool]) -> Optional[int]:
    for port in (base, *(base + n for n in RESERVE_SPAN)):
        if port <= 65535 and free(port):
            return port
    return None


class MemberListener:

    EVICT_OLDEST = True
    HANDSHAKE_TIMEOUT = MEMBER_HANDSHAKE_TIMEOUT

    def __init__(self, *, identity: LinkIdentity, rendezvous: Rendezvous, host: str = "0.0.0.0",
                 on_state: Optional[Callable[[str], None]] = None,
                 follow_hello: Optional[Callable[[], Awaitable[Optional[Dict[str, Any]]]]] = None) -> None:
        self._identity, self._rv, self._host, self._on_state = identity, rendezvous, host, on_state
        self._follow_hello = follow_hello
        self._follow_shas: frozenset = frozenset()
        self._gate = _HandshakeGate(MESH_PER_SOURCE, MESH_TOTAL) if capabilities.mesh_on() else _HandshakeGate(PER_SOURCE_HANDSHAKES, TOTAL_HANDSHAKES)
        self._mesh_accept: Optional[Callable[[asyncio.StreamReader, asyncio.StreamWriter, str], Awaitable[None]]] = None
        self._mesh_iid: Optional[Callable[[str], Optional[str]]] = None
        self._ctx: Optional[ssl.SSLContext] = None
        self._shas: frozenset = frozenset()
        self._server: Optional[asyncio.AbstractServer] = None
        self.port: Optional[int] = None
        self.state = STOPPED

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            if self._on_state is not None:
                self._on_state(state)

    async def reserve(self, base: int = DEFAULT_LINK_PORT) -> Optional[int]:
        if self._server is not None:
            return self.port
        port = reserve_listen_port(base, lambda port: _port_free(port, self._host))
        if port is None:
            self._set_state(PORT_BUSY)
            return None
        await self.bind(port)
        return self.port

    async def bind(self, port: int) -> bool:
        if self._server is not None:
            return True
        loop = asyncio.get_running_loop()
        try:
            self._server = await _TlsGate.open(self, loop, self._host, port)
        except OSError as exc:
            log.warning("member_listener_bind_failed", port=port, error=type(exc).__name__)
            self._set_state(PORT_BUSY)
            return False
        self.port = self._server.sockets[0].getsockname()[1]
        self._set_state(LISTENING)
        return True

    def attach_mesh(self, accept: Callable[[asyncio.StreamReader, asyncio.StreamWriter, str], Awaitable[None]],
                    iid_for_sha: Callable[[str], Optional[str]]) -> None:
        self._mesh_accept, self._mesh_iid = accept, iid_for_sha
        if self._ctx is not None:
            self._ctx.set_alpn_protocols([MESH_ALPN])

    def detach_mesh(self) -> None:
        self._mesh_accept = self._mesh_iid = None

    async def set_pins(self, pins: Sequence[LinkCert], follow_pins: Sequence[LinkCert] = ()) -> None:
        shas = frozenset(c.cert_sha256 for c in pins)
        extra = [c for c in follow_pins if c.cert_sha256 not in shas]
        ctx = await asyncio.to_thread(server_link_ctx, self._identity, [*pins, *extra]) if (pins or extra) else None
        if ctx is not None:
            if self._mesh_accept is not None:
                ctx.set_alpn_protocols([MESH_ALPN])
            ctx.sslobject_class = AlertingSSLObject
        self._ctx = ctx
        self._shas = shas
        self._follow_shas = frozenset(c.cert_sha256 for c in extra) if ctx is not None else frozenset()

    async def stop(self) -> None:
        server, self._server, self._ctx, self._shas, self.port = self._server, None, None, frozenset(), None
        self._follow_shas = frozenset()
        if server is not None:
            server.close()
        self._rv.close()
        self._set_state(STOPPED)

    async def _on_tls_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        ssl_obj = writer.get_extra_info("ssl_object")
        der = ssl_obj.getpeercert(binary_form=True) if ssl_obj is not None else None
        sha = hashlib.sha256(der).hexdigest() if der else ""
        if self._mesh_accept is not None and self._mesh_iid is not None:
            try:
                alpn = ssl_obj.selected_alpn_protocol() if ssl_obj is not None else None
            except ValueError:
                alpn = None
            if alpn == MESH_ALPN:
                iid = self._mesh_iid(sha) if der else None
                if iid is None:
                    log.info("member_listener_mesh_refused", sha=sha[:12])
                    writer.close()
                    return
                await self._mesh_accept(reader, writer, iid)
                return
        if sha in self._follow_shas and sha not in self._shas:
            await self._answer_follow(reader, writer)
            return
        if not der or sha not in self._shas:
            log.info("member_listener_handshake_failed", why="not_pinned")
            writer.close()
            return
        self._rv.offer(reader, writer)

    async def _answer_follow(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            extras = await self._follow_hello() if self._follow_hello is not None else None
            if not extras:
                writer.close()
                return
            session = MuxSession(reader, writer, dialer=True)
            await session.start({"v": mf.PROTOCOL_VERSION, "proto": PROTOCOL_MAJOR, **extras})
            await session.close(mf.GO_NORMAL)
        except (MuxError, OSError, ValueError) as exc:
            log.info("member_listener_follow_failed", why=type(exc).__name__)
            writer.close()


def _port_free(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True

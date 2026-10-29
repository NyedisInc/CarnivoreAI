
from __future__ import annotations

import asyncio
import hashlib
import socket
import ssl
from typing import Callable, Optional, Sequence, Tuple

import structlog

from src.core.computers.link_listener import DEFAULT_LINK_PORT, AlertingSSLObject, _HandshakeGate, _TlsGate
from src.core.computers.tls_identity import LinkCert, LinkIdentity, server_link_ctx

log = structlog.get_logger(__name__)

PER_SOURCE_HANDSHAKES = 2
TOTAL_HANDSHAKES = 8
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

    def offer(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._drop()
        self._slot = (reader, writer)
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
                 on_state: Optional[Callable[[str], None]] = None) -> None:
        self._identity, self._rv, self._host, self._on_state = identity, rendezvous, host, on_state
        self._gate = _HandshakeGate(PER_SOURCE_HANDSHAKES, TOTAL_HANDSHAKES)
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

    async def set_pins(self, pins: Sequence[LinkCert]) -> None:
        ctx = await asyncio.to_thread(server_link_ctx, self._identity, pins) if pins else None
        if ctx is not None:
            ctx.sslobject_class = AlertingSSLObject
        self._ctx = ctx
        self._shas = frozenset(c.cert_sha256 for c in pins)

    async def stop(self) -> None:
        server, self._server, self._ctx, self._shas, self.port = self._server, None, None, frozenset(), None
        if server is not None:
            server.close()
        self._rv.close()
        self._set_state(STOPPED)

    async def _on_tls_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        ssl_obj = writer.get_extra_info("ssl_object")
        der = ssl_obj.getpeercert(binary_form=True) if ssl_obj is not None else None
        if not der or hashlib.sha256(der).hexdigest() not in self._shas:
            log.info("member_listener_handshake_failed", why="not_pinned")
            writer.close()
            return
        self._rv.offer(reader, writer)


def _port_free(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import socket
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional, Type

import structlog
import uvicorn
from uvicorn.protocols.http.h11_impl import H11Protocol

logger = structlog.get_logger()

MAX_HEAD_BYTES = 16 * 1024
MAX_CONCURRENCY = 64
REQUEST_DEADLINE_SECONDS = 10.0
KEEP_ALIVE_SECONDS = 2
START_TIMEOUT_SECONDS = 5.0
STOP_TIMEOUT_SECONDS = 5.0


def canonical_ip(text: str) -> Optional[str]:
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    mapped = getattr(address, "ipv4_mapped", None)
    return str(mapped if mapped is not None else address)


class PublicListenerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ListenerSpec:

    host: str
    port: int
    request_deadline: float = REQUEST_DEADLINE_SECONDS
    peer_allowed: Optional[Callable[[str], bool]] = None
    max_concurrency: int = MAX_CONCURRENCY
    max_head_bytes: int = MAX_HEAD_BYTES

    def __post_init__(self) -> None:
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError as exc:
            raise PublicListenerError(f"listener host {self.host!r} is not an IP address") from exc
        if address.is_unspecified or address.is_multicast:
            raise PublicListenerError(f"listener host {self.host!r} is not one specific interface")
        if not 0 <= self.port <= 65535:
            raise PublicListenerError(f"listener port {self.port!r} is out of range")


def peer_refused(spec: ListenerSpec, transport: Any) -> bool:
    if spec.peer_allowed is None:
        return False
    peer = transport.get_extra_info("peername")
    return not (isinstance(peer, tuple) and bool(peer) and spec.peer_allowed(str(peer[0])))


def deadline_protocol(spec: ListenerSpec) -> Type[H11Protocol]:

    class DeadlineProtocol(H11Protocol):

        _deadline_handle: Optional[asyncio.TimerHandle] = None

        def connection_made(self, transport: Any) -> None:  # type: ignore[override]
            if peer_refused(spec, transport):
                transport.abort()
                return
            super().connection_made(transport)
            self._deadline_handle = asyncio.get_running_loop().call_later(spec.request_deadline, transport.abort)

        def connection_lost(self, exc: Optional[Exception]) -> None:
            if self._deadline_handle is not None:
                self._deadline_handle.cancel()
                super().connection_lost(exc)

    return DeadlineProtocol


class _NoSignalServer(uvicorn.Server):

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


def build_config(app: Any, spec: ListenerSpec) -> uvicorn.Config:
    return uvicorn.Config(
        app, host=spec.host, port=spec.port, http=deadline_protocol(spec), ws="none", lifespan="off",
        interface="asgi3", proxy_headers=False, server_header=False, access_log=False, log_level="warning", log_config=None,
        limit_concurrency=spec.max_concurrency, timeout_keep_alive=KEEP_ALIVE_SECONDS, h11_max_incomplete_event_size=spec.max_head_bytes)


class PublicListener:

    def __init__(self, app: Any, spec: ListenerSpec) -> None:
        self.spec = spec
        self._server = _NoSignalServer(build_config(app, spec))
        self._task: Optional["asyncio.Task[None]"] = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done() and bool(self._server.started)

    @property
    def port(self) -> int:
        servers = getattr(self._server, "servers", None) or []
        for server in servers:
            for sock in server.sockets:
                return int(sock.getsockname()[1])
        raise PublicListenerError("the public listener is not bound")

    def _bind(self) -> socket.socket:
        family = socket.AF_INET6 if ":" in self.spec.host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.spec.host, self.spec.port))
        except OSError as exc:
            sock.close()
            raise PublicListenerError(f"cannot bind the public listener to {self.spec.host}:{self.spec.port}: {exc.strerror or exc}") from exc
        return sock

    async def start(self, timeout: float = START_TIMEOUT_SECONDS) -> None:
        sock = self._bind()
        self._task = asyncio.create_task(self._server.serve(sockets=[sock]), name="publicboard-listener")
        try:
            await self._wait_started(timeout)
        except BaseException:
            await self.stop()
            sock.close()
            raise
        logger.info("publicboard_listener_started", host=self.spec.host, port=self.port)

    async def _wait_started(self, timeout: float) -> None:
        if self._task is None:
            raise PublicListenerError("the public listener has no server task")
        deadline = asyncio.get_running_loop().time() + timeout
        while not self._server.started:
            if self._task.done() or asyncio.get_running_loop().time() > deadline:
                raise PublicListenerError(f"the public listener did not start on {self.spec.host}:{self.spec.port}")
            await asyncio.sleep(0.02)

    async def stop(self) -> None:
        self._server.should_exit = True
        task, self._task = self._task, None
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=STOP_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("publicboard_listener_stop_timeout")
            task.cancel()
        logger.info("publicboard_listener_stopped", host=self.spec.host)

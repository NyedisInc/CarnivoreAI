
from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Dict, Optional, Tuple

import structlog
import uvicorn

from src.core.computers import mesh
from src.core.computers.mux import frames as mf
from src.core.computers.mux.session import MuxSession, MuxStream, bridge
from src.core.federation.peer_listener import PeerLinkTag, _NoSignalServer


class MeshListenerRuntimeError(RuntimeError):
    pass


log = structlog.get_logger(__name__)

MESH_PUBLIC = frozenset({"/api/v1/federation/mesh/token"})
CONNECT_TIMEOUT = 5.0


class MeshPortTable:

    def __init__(self) -> None:
        self._by_port: Dict[int, Tuple[str, MuxSession]] = {}

    def add(self, port: int, peer: str, mux: MuxSession) -> None:
        self._by_port[port] = (peer, mux)

    def remove(self, port: int, mux: MuxSession) -> None:
        found = self._by_port.get(port)
        if found is not None and found[1] is mux:
            del self._by_port[port]

    def lookup(self, port: int) -> Optional[Tuple[str, MuxSession]]:
        return self._by_port.get(port)

    def __len__(self) -> int:
        return len(self._by_port)


class MeshTag:

    def __init__(self, app: Any, table: MeshPortTable) -> None:
        self.app, self._table = app, table

    def _peer_of(self, scope: Any) -> Optional[str]:
        client = scope.get("client")
        found = self._table.lookup(client[1]) if client and len(client) > 1 and client[0] == "127.0.0.1" else None
        if found is None:
            return None
        peer, mux = found
        return peer if mesh.current_mux(peer) is mux else None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            peer = self._peer_of(scope)
            if peer is None:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 4403})
                else:
                    await send({"type": "http.response.start", "status": 403, "headers": []})
                    await send({"type": "http.response.body", "body": b""})
                return
            scope = dict(scope, client=None, mesh_peer=peer)
        await self.app(scope, receive, send)


class MeshListener:

    def __init__(self, app: Any) -> None:
        self.table = MeshPortTable()
        self._server = _NoSignalServer(uvicorn.Config(
            MeshTag(PeerLinkTag(app, public=MESH_PUBLIC), self.table), host="127.0.0.1", port=0, lifespan="off", log_level="warning",
            access_log=False, proxy_headers=False, ws="websockets", log_config=None))
        self._task: Optional["asyncio.Task[None]"] = None
        self.port: int = 0

    async def start(self, timeout: float = 5.0) -> None:
        self._task = asyncio.create_task(self._server.serve(), name="mesh-listener")
        deadline = asyncio.get_running_loop().time() + timeout
        while not self._server.started:
            if self._task.done() or asyncio.get_running_loop().time() > deadline:
                raise MeshListenerRuntimeError("the mesh listener did not start")
            await asyncio.sleep(0.02)
        self.port = self._server.servers[0].sockets[0].getsockname()[1]
        log.info("mesh_listener_started")

    async def stop(self) -> None:
        self._server.should_exit = True
        if self._task is not None:
            with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self._task, timeout=5)
        self.port = 0


_LISTENER: Optional[MeshListener] = None


async def start(app: Any) -> None:
    global _LISTENER
    if _LISTENER is None:
        _LISTENER = MeshListener(app)
        try:
            await _LISTENER.start()
        except RuntimeError:
            _LISTENER = None
            raise


async def stop() -> None:
    global _LISTENER
    listener, _LISTENER = _LISTENER, None
    if listener is not None:
        await listener.stop()


def port() -> int:
    return _LISTENER.port if _LISTENER is not None else 0


async def bridge_inbound(stream: MuxStream, peer: str, mux: MuxSession) -> None:
    listener = _LISTENER
    if listener is None or not listener.port:
        stream.reset(mf.RST_UNAVAILABLE)
        return
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", listener.port), CONNECT_TIMEOUT)
    except (OSError, asyncio.TimeoutError):
        stream.reset(mf.RST_UNAVAILABLE)
        return
    sockname = writer.get_extra_info("sockname")
    if not sockname:
        writer.close()
        stream.reset(mf.RST_UNAVAILABLE)
        return
    table, local = listener.table, sockname[1]
    table.add(local, peer, mux)
    try:
        await bridge(stream, reader, writer)
    finally:
        table.remove(local, mux)
        writer.close()


from __future__ import annotations

import asyncio
import os
import stat
from typing import Awaitable, Callable

import structlog

from src.core.computers.mux import frames as f
from src.core.computers.mux.session import MuxError, MuxSession, MuxStream, bridge

log = structlog.get_logger(__name__)

OPEN_CONNECT_TIMEOUT = 5.0


def inbound_handler(listener_path: str) -> Callable[[MuxStream], Awaitable[None]]:
    async def on_open(stream: MuxStream) -> None:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(listener_path), OPEN_CONNECT_TIMEOUT)
        except (OSError, asyncio.TimeoutError):
            stream.reset(f.RST_UNAVAILABLE)
            return
        await bridge(stream, reader, writer)
    return on_open


class LocalSocket:

    def __init__(self, session: MuxSession, path: str) -> None:
        self.session, self.path = session, path
        self._server: asyncio.AbstractServer | None = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            stream = await self.session.open("peer-api")
        except MuxError as exc:
            log.info("link_local_open_refused", why=str(exc))
            writer.close()
            return
        await bridge(stream, reader, writer)

    async def start(self) -> None:
        try:
            if stat.S_ISSOCK(os.lstat(self.path).st_mode):
                os.unlink(self.path)
        except FileNotFoundError:
            pass
        self._server = await asyncio.start_unix_server(self._handle, path=self.path)
        os.chmod(self.path, 0o600)

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            try:
                await asyncio.wait_for(server.wait_closed(), 2.0)
            except asyncio.TimeoutError:
                log.warning("link_local_socket_close_slow")
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


from __future__ import annotations

import asyncio
import contextlib
import socket
import ssl
from typing import Any, Optional

import structlog
import uvicorn

from src.core.federation.peer_listener import _NoSignalServer

logger = structlog.get_logger()


class LoopbackListener:

    def __init__(self, app: Any, context: ssl.SSLContext) -> None:
        self._sock: Optional[socket.socket] = None
        self._task: Optional["asyncio.Task[None]"] = None
        config = uvicorn.Config(app, lifespan="off", log_level="warning", access_log=False,
                                proxy_headers=False, ws="websockets", timeout_keep_alive=30,
                                log_config=None)
        config.load()
        config.ssl = context
        self._server = _NoSignalServer(config)

    @property
    def port(self) -> int:
        if self._sock is None:
            raise RuntimeError("the link listener is not started")
        return self._sock.getsockname()[1]

    async def start(self, timeout: float = 5.0) -> None:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self._sock = sock
        self._task = asyncio.create_task(self._server.serve(sockets=[sock]), name="phone-link-listener")
        deadline = asyncio.get_running_loop().time() + timeout
        while not self._server.started:
            if self._task.done() or asyncio.get_running_loop().time() > deadline:
                raise RuntimeError("mobile sync listener did not start")
            await asyncio.sleep(0.02)
        logger.info("phone_link_listener_started")

    async def stop(self) -> None:
        self._server.should_exit = True
        if self._task is not None:
            with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self._task, timeout=5)
        if self._sock is not None:
            self._sock.close()
            self._sock = None

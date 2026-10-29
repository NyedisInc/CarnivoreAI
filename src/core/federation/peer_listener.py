
from __future__ import annotations

import asyncio
import contextlib
import os
import stat
from pathlib import Path
from typing import Any, Iterator, Optional, Tuple

import structlog
import uvicorn

logger = structlog.get_logger()

SOCKET_NAME_PREFIX = "peer-"


class PeerLinkTag:

    def __init__(self, app: Any) -> None:
        self.app = app
        self._allowed: Optional[list] = None

    def _permits(self, scope: Any) -> bool:
        if self._allowed is None:
            self._allowed = peer_allowed_routes(self.app)
        return any(rx.match(scope["path"]) for rx in self._allowed)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            scope["via_peer_link"] = True
            if not self._permits(scope):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 4404})
                else:
                    await send({"type": "http.response.start", "status": 404, "headers": []})
                    await send({"type": "http.response.body", "body": b""})
                return
        await self.app(scope, receive, send)


class _NoSignalServer(uvicorn.Server):

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


def socket_path_for(directory: Path, instance_tag: str) -> str:
    return str(directory / f"{SOCKET_NAME_PREFIX}{instance_tag}.sock")


class PeerListener:

    def __init__(self, app: Any, path: str) -> None:
        self.path = path
        self._server = _NoSignalServer(uvicorn.Config(
            PeerLinkTag(app), uds=path, lifespan="off", log_level="warning", access_log=False,
            proxy_headers=False, ws="websockets",
            log_config=None))
        self._task: Optional["asyncio.Task[None]"] = None

    async def start(self, timeout: float = 5.0) -> None:
        directory = Path(self.path).parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        with contextlib.suppress(FileNotFoundError):
            if stat.S_ISSOCK(os.lstat(self.path).st_mode):
                os.unlink(self.path)
        self._task = asyncio.create_task(self._server.serve(), name="peer-listener")
        deadline = asyncio.get_running_loop().time() + timeout
        while not self._server.started:
            if self._task.done() or asyncio.get_running_loop().time() > deadline:
                raise RuntimeError("the peer-link listener did not start")
            await asyncio.sleep(0.02)
        os.chmod(self.path, 0o600)
        logger.info("peer_listener_started")

    async def stop(self) -> None:
        self._server.should_exit = True
        if self._task is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._task, timeout=5)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.path)


def peer_allowed_routes(app: Any) -> list:
    from fastapi.routing import APIRoute, APIWebSocketRoute
    from starlette.routing import compile_path

    def calls(dependant: Any) -> Iterator[Any]:
        yield dependant.call
        for sub in dependant.dependencies:
            yield from calls(sub)

    def walk(routes: Any, prefix: str = "") -> Iterator[Tuple[str, Any]]:
        for route in routes:
            if hasattr(route, "original_router"):
                yield from walk(route.original_router.routes, prefix + (route.include_context.prefix or ""))
            elif isinstance(route, (APIRoute, APIWebSocketRoute)):
                yield prefix + route.path, route
            elif hasattr(route, "routes"):
                yield from walk(route.routes, prefix)

    public = {"/api/v1/federation/token", "/api/v1/federation/prove"}
    return [compile_path(path)[0] for path, r in walk(app.routes)
            if path in public or any(hasattr(c, "peer_scope") for c in calls(r.dependant))]

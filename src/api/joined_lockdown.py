
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from starlette.types import ASGIApp, Receive, Scope, Send

from src.api.enrollment_gate import is_loopback_host
from src.core.setup_state import joined_marker_path

STAT_CACHE_S = 2.0
_BODY = json.dumps({"detail": {"reason": "joined_local_only"}}).encode("ascii")


def _default_marker() -> Path:
    from src.config import settings  # noqa: PLC0415

    return joined_marker_path(Path(settings.auth_config_file).expanduser())


class JoinedLockdownMiddleware:

    def __init__(self, app: ASGIApp, marker: Callable[[], Path] = _default_marker,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.app = app
        self._marker = marker
        self._clock = clock
        self._checked_at: Optional[float] = None
        self._joined = False

    def _is_joined(self) -> bool:
        now = self._clock()
        if self._checked_at is None or now - self._checked_at >= STAT_CACHE_S or now < self._checked_at:
            try:
                self._joined = self._marker().exists()
            except OSError:
                self._joined = True
            self._checked_at = now
        return self._joined

    @staticmethod
    def _allowed(scope: Scope) -> bool:
        if scope.get("via_link"):
            return False
        if scope.get("via_peer_link"):
            return True
        client = scope.get("client")
        return bool(client) and is_loopback_host(client[0])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and self._is_joined() and not self._allowed(scope):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 4403})
                return
            headers: list[Any] = [(b"content-type", b"application/json"), (b"cache-control", b"no-store"),
                                  (b"content-length", str(len(_BODY)).encode("ascii"))]
            await send({"type": "http.response.start", "status": 403, "headers": headers})
            await send({"type": "http.response.body", "body": _BODY})
            return
        await self.app(scope, receive, send)


from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Mapping, MutableMapping, Optional

import structlog

from src.core import graceful_shutdown
from src.core.perf_hooks.monitor import PERF

logger = structlog.get_logger()

LOG_EXTRA_KEY = "log_extra"
_STATIC_PREFIXES = ("/static/",)
_STATIC_SUFFIXES = (".js", ".css", ".map", ".png", ".woff2")
_QUIET_PATHS = ("/api/v1/server-log",)

ASGIApp = Callable[[MutableMapping[str, Any], Callable, Callable], Awaitable[None]]


def _is_static_asset(path: str) -> bool:
    return path.startswith(_STATIC_PREFIXES) or path.endswith(_STATIC_SUFFIXES) or path in _QUIET_PATHS


def _client_ip(scope: MutableMapping[str, Any]) -> Optional[str]:
    client = scope.get("client")
    if not client:
        return None
    return client[0]


class RequestLogMiddleware:

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[MutableMapping[str, Any]]],
        send: Callable[[MutableMapping[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        client_ip = _client_ip(scope)
        status: Optional[int] = None

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        started = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        except asyncio.CancelledError:
            if graceful_shutdown.is_shutting_down():
                logger.info("request_cancelled_at_shutdown", method=method, path=path, client_ip=client_ip,
                            duration_ms=round((time.perf_counter() - started) * 1000, 2))
            raise
        except Exception:
            self._log(method, path, client_ip, 500, started, scope.get(LOG_EXTRA_KEY))
            raise
        else:
            self._log(method, path, client_ip, status, started, scope.get(LOG_EXTRA_KEY))
        finally:
            if PERF.enabled:
                route = scope.get("route")
                PERF.record_request(method, getattr(route, "path", None) or path,
                                    (time.perf_counter() - started) * 1000.0)

    @staticmethod
    def _log(
        method: str,
        path: str,
        client_ip: Optional[str],
        status: Optional[int],
        started: float,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> None:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        level = "debug" if _is_static_asset(path) else "info"
        getattr(logger, level)(
            "http_request",
            method=method,
            path=path,
            status=status,
            client_ip=client_ip,
            duration_ms=duration_ms,
            **(extra or {}),
        )

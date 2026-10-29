
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

ROLLUP_INTERVAL_S = 300.0
SLOW_REQUEST_MS = 1000.0
_ROLLUP_MAX_KEYS = 500
_READ_METHODS = frozenset({"GET", "HEAD"})

ASGIApp = Callable[[MutableMapping[str, Any], Callable, Callable], Awaitable[None]]


def _is_static_asset(path: str) -> bool:
    return path.startswith(_STATIC_PREFIXES) or path.endswith(_STATIC_SUFFIXES) or path in _QUIET_PATHS


def _client_ip(scope: MutableMapping[str, Any]) -> Optional[str]:
    client = scope.get("client")
    if not client:
        return None
    return client[0]


def _is_auth_path(path: str) -> bool:
    return "/auth/" in path or path.endswith("/auth") or "login" in path


def _is_routine(method: str, path: str, status: Optional[int], duration_ms: float, extra: Optional[Mapping[str, Any]]) -> bool:
    if status is None or status >= 400 or duration_ms >= SLOW_REQUEST_MS or _is_auth_path(path):
        return False
    if method in _READ_METHODS:
        return True
    return method == "POST" and bool(extra) and extra.get("rpc") == "ping"


class _Rollup:

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.started = time.monotonic()
        self.buckets: dict[tuple[str, str, str], list[float]] = {}

    def add(self, method: str, path: str, rpc: str, duration_ms: float) -> None:
        key = (method, path, rpc)
        if key not in self.buckets and len(self.buckets) >= _ROLLUP_MAX_KEYS:
            key = (method, "(other)", rpc)
        b = self.buckets.setdefault(key, [0, 0.0, 0.0])
        b[0] += 1
        b[1] += duration_ms
        b[2] = max(b[2], duration_ms)
        if time.monotonic() - self.started >= ROLLUP_INTERVAL_S:
            self.flush()

    def flush(self) -> None:
        if self.buckets:
            window_s = round(time.monotonic() - self.started, 1)
            routes = [
                {"method": m, "path": p, "rpc": r, "count": int(c), "total_ms": round(t, 1), "avg_ms": round(t / c, 1),
                 "max_ms": round(mx, 1)}
                for (m, p, r), (c, t, mx) in sorted(self.buckets.items(), key=lambda kv: -kv[1][0])
            ]
            logger.info("http_request_rollup", window_s=window_s, requests=sum(r["count"] for r in routes), routes=routes)
        self.reset()


_ROLLUP = _Rollup()


def flush_rollup() -> None:
    _ROLLUP.flush()


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
            self._log(method, path, client_ip, status, started, scope.get(LOG_EXTRA_KEY), scope.get("route"))
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
        route: Any = None,
    ) -> None:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        is_static = _is_static_asset(path)
        if not is_static and _is_routine(method, path, status, duration_ms, extra):
            _ROLLUP.add(method, getattr(route, "path", None) or path, str((extra or {}).get("rpc", "")), duration_ms)
            return
        level = "debug" if is_static else "info"
        getattr(logger, level)(
            "http_request",
            method=method,
            path=path,
            status=status,
            client_ip=client_ip,
            duration_ms=duration_ms,
            **(extra or {}),
        )

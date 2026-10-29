
from __future__ import annotations

import gzip
from typing import Any, Awaitable, Callable, Dict, List, MutableMapping, Optional

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

MIN_BYTES = 8 * 1024
LEVEL = 4


def _header(headers: List[tuple], name: bytes) -> Optional[bytes]:
    return next((v for k, v in headers if k.lower() == name), None)


def _accepts_gzip(scope: Scope) -> bool:
    value = _header(list(scope.get("headers", [])), b"accept-encoding")
    return value is not None and b"gzip" in value.lower()


class JsonGzipMiddleware:

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _accepts_gzip(scope):
            await self.app(scope, receive, send)
            return
        start: Dict[str, Any] = {}
        chunks: List[bytes] = []
        buffering = False

        async def wrapped(message: MutableMapping[str, Any]) -> None:
            nonlocal buffering
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                kind = _header(headers, b"content-type") or b""
                buffering = (message["status"] == 200 and kind.lower().startswith(b"application/json")
                             and _header(headers, b"content-encoding") is None)
                if buffering:
                    start.update(message)
                    return
            elif buffering and message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                body = b"".join(chunks)
                if len(body) >= MIN_BYTES:
                    body = gzip.compress(body, LEVEL)
                    start["headers"] = [(k, v) for k, v in start["headers"] if k.lower() not in (b"content-length", b"vary")] + [
                        (b"content-encoding", b"gzip"), (b"vary", b"Accept-Encoding"), (b"content-length", str(len(body)).encode())]
                await send(start)
                await send({"type": "http.response.body", "body": body})
                return
            await send(message)

        await self.app(scope, receive, wrapped)

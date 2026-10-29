
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, FrozenSet, Iterable, List, Mapping, Optional, Tuple

from src.cplugs.publicboard.headers import api_headers, as_asgi
from src.cplugs.publicboard.routes import ROUTES, Handler, RouteKey
from src.cplugs.sdk.public_listener import MAX_HEAD_BYTES, canonical_ip

FORBIDDEN, BAD_REQUEST, NOT_FOUND, LENGTH_REQUIRED, TOO_LARGE, UNSUPPORTED_TYPE, MISDIRECTED, HEAD_TOO_LARGE = 403, 400, 404, 411, 413, 415, 421, 431
TARGET_CHARS = re.compile(rb"/[A-Za-z0-9/._-]*", re.ASCII)
MAX_TARGET_BYTES = 256
MAX_BODY_BYTES = 64 * 1024
JSON_TYPE = b"application/json"
_DIGITS = re.compile(rb"[0-9]{1,7}", re.ASCII)
WS_REFUSED = 1008


@dataclass(frozen=True)
class EdgeConfig:

    trusted_proxies: FrozenSet[str]
    hostnames: FrozenSet[str]

    @classmethod
    def of(cls, trusted_proxies: Iterable[str], hostnames: Iterable[str]) -> "EdgeConfig":
        peers = []
        for entry in trusted_proxies:
            canon = canonical_ip(entry)
            if canon is None:
                raise ValueError(f"trusted proxy {entry!r} is not an IP address")
            peers.append(canon)
        return cls(frozenset(peers), frozenset(hostnames))


def _header_values(scope: Any, name: bytes) -> List[bytes]:
    return [value for key, value in scope.get("headers") or () if key == name]


def peer_refusal(scope: Any, config: EdgeConfig) -> Optional[int]:
    client = scope.get("client")
    peer = canonical_ip(client[0]) if client else None
    return None if peer is not None and peer in config.trusted_proxies else FORBIDDEN


def host_refusal(scope: Any, config: EdgeConfig) -> Optional[int]:
    values = _header_values(scope, b"host")
    if len(values) != 1:
        return MISDIRECTED
    try:
        host = values[0].decode("ascii")
    except UnicodeDecodeError:
        return MISDIRECTED
    return None if host in config.hostnames else MISDIRECTED


def target_refusal(scope: Any) -> Optional[int]:
    raw = scope.get("raw_path")
    if not isinstance(raw, bytes) or len(raw) > MAX_TARGET_BYTES or scope.get("query_string"):
        return BAD_REQUEST
    if not TARGET_CHARS.fullmatch(raw) or b"//" in raw or b".." in raw:
        return BAD_REQUEST
    if any(segment == b"." for segment in raw.split(b"/")):
        return BAD_REQUEST
    return None


def head_refusal(scope: Any) -> Optional[int]:
    size = sum(len(name) + len(value) + 4 for name, value in scope.get("headers") or ())
    return HEAD_TOO_LARGE if size > MAX_HEAD_BYTES else None


def route_for(scope: Any, routes: Mapping[RouteKey, Handler]) -> Optional[Handler]:
    return routes.get((str(scope.get("method")), scope["raw_path"].decode("ascii")))


def header_refusal(scope: Any) -> Optional[int]:
    if _header_values(scope, b"transfer-encoding"):
        return BAD_REQUEST
    lengths = _header_values(scope, b"content-length")
    if len(lengths) > 1 or any(not _DIGITS.fullmatch(v) for v in lengths):
        return BAD_REQUEST
    size = int(lengths[0]) if lengths else None
    if scope.get("method") != "POST":
        return BAD_REQUEST if size else None
    if size is None:
        return LENGTH_REQUIRED
    if size > MAX_BODY_BYTES:
        return TOO_LARGE
    return None if _header_values(scope, b"content-type") == [JSON_TYPE] else UNSUPPORTED_TYPE


async def refuse(send: Any, status: int) -> None:
    headers = as_asgi(api_headers()) + [(b"content-length", b"0"), (b"connection", b"close")]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": b""})


class PublicEdge:

    def __init__(self, config: EdgeConfig, routes: Mapping[RouteKey, Handler] = ROUTES) -> None:
        self.config = config
        self.routes = routes

    async def _refuse_websocket(self, receive: Any, send: Any) -> None:
        await receive()
        await send({"type": "websocket.close", "code": WS_REFUSED})

    def _refusal(self, scope: Any) -> Tuple[Optional[int], Optional[Handler]]:
        status = peer_refusal(scope, self.config) or host_refusal(scope, self.config) or target_refusal(scope) or head_refusal(scope)
        if status is not None:
            return status, None
        handler = route_for(scope, self.routes)
        if handler is None:
            return NOT_FOUND, None
        return header_refusal(scope), handler

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "websocket":
            await self._refuse_websocket(receive, send)
            return
        if scope["type"] != "http":
            return
        status, handler = self._refusal(scope)
        if status is not None or handler is None:
            await refuse(send, status or NOT_FOUND)
            return
        await handler(scope, receive, send)

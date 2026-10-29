
from __future__ import annotations

from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

from src.core.phone_link.pairing import PairingStore

logger = structlog.get_logger()

COOKIE_NAME = "__Host-cc_link"
PENDING_COOKIE_NAME = "__Host-cc_pair"

DENIED_PREFIXES = (
    "/api/v1/hosts", "/api/v1/federation", "/mcp", "/api/v1/phone-link",
    "/api/v1/auth/qr", "/api/v1/auth/enrollment", "/api/v1/setup", "/setup",
    "/api/v1/auth/join", "/api/v1/computers/add", "/api/v1/computers/peers", "/api/v1/computers/join",
    "/api/v1/computers/leave",
)

STRIPPED_HEADERS = (b"x-forwarded-for", b"forwarded", b"x-real-ip", b"x-forwarded-host",
                    b"x-forwarded-proto", b"x-forwarded-port", b"x-forwarded-server", b"via",
                    b"cf-connecting-ip", b"true-client-ip", b"x-client-ip", b"x-original-host")

PUBLIC_PATHS = frozenset({
    "/pair", "/pair/status", "/pair/claim", "/pair/code", "/pair/verify", "/manifest.webmanifest",
    "/static/dist/pair.js", "/static/dist/pair.css",
    "/static/fonts/jetbrains-mono/JetBrainsMono-Regular.woff2",
    "/static/fonts/jetbrains-mono/JetBrainsMono-Medium.woff2",
    "/static/fonts/jetbrains-mono/JetBrainsMono-Bold.woff2",
    "/static/assets/icons/icon-180.png", "/static/assets/icons/icon-192.png",
    "/static/assets/icons/icon-512.png", "/static/assets/icons/icon-512-maskable.png",
})

Send = Callable[[Dict[str, Any]], Awaitable[None]]


@dataclass
class LinkStream:

    stream_id: int
    client_ip: str
    client_port: int
    request_seen: bool = False
    trusted: bool = False
    device: Optional[str] = None
    sni: str = ""


class StreamTable:

    def __init__(self) -> None:
        self._by_port: Dict[int, LinkStream] = {}

    def add(self, port: int, stream: LinkStream) -> None:
        self._by_port[port] = stream

    def remove(self, port: int) -> None:
        self._by_port.pop(port, None)

    def lookup(self, port: int) -> Optional[LinkStream]:
        return self._by_port.get(port)

    def for_device(self, device_id: str) -> List[LinkStream]:
        return [s for s in self._by_port.values() if s.device == device_id]


def _header(scope: Dict[str, Any], name: bytes) -> Optional[str]:
    for key, value in scope.get("headers", ()):
        if key == name:
            return value.decode("latin-1")
    return None


def read_cookie(scope: Dict[str, Any], name: str = COOKIE_NAME) -> Optional[str]:
    raw = _header(scope, b"cookie")
    if not raw:
        return None
    jar: SimpleCookie = SimpleCookie()
    try:
        jar.load(raw)
    except CookieError:
        return None
    morsel = jar.get(name)
    return morsel.value if morsel else None


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS


def has_control(value: str) -> bool:
    return any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)


def normalise_path(path: str) -> Optional[str]:
    if has_control(path):
        return None
    segments = [seg for seg in path.split("/") if seg not in ("", ".")]
    if ".." in segments:
        return None
    return "/" + "/".join(segments).lower() + ("/" if path.endswith("/") and segments else "")


def is_denied(path: str) -> bool:
    lowered = normalise_path(path)
    if lowered is None:
        return True
    return any(lowered == p or lowered.startswith(p + "/") for p in DENIED_PREFIXES)


class LinkGate:

    def __init__(self, app: Any, *, hostname: str, streams: StreamTable, pairing: PairingStore,
                 send_trust: Callable[[int], None],
                 custom_host: Callable[[], Optional[str]] = lambda: None) -> None:
        self.app = app
        self._hostname = hostname.lower()
        self._custom_host = custom_host
        self._streams = streams
        self._pairing = pairing
        self._send_trust = send_trust

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        stream = self._streams.lookup(client[1]) if client else None
        if stream is None:
            await self._refuse(scope, send, 403, "not from the tunnel")
            return
        scope["client"] = (stream.client_ip, stream.client_port)
        scope["via_link"] = True
        scope["headers"] = [(k, v) for k, v in scope.get("headers", ()) if k.lower() not in STRIPPED_HEADERS]
        host = (_header(scope, b"host") or "").lower()
        if host.endswith(":443"):
            host = host[:-4]
        custom = self._custom_host()
        if host not in (self._hostname, custom) or (stream.sni or self._hostname).lower() != host:
            await self._refuse(scope, send, 421, "misdirected request")
            return
        scope["link_host"] = host
        path = scope.get("path", "")
        raw = scope.get("raw_path") or b""
        if has_control(path) or has_control(raw.decode("latin-1")) or normalise_path(path) is None:
            await self._refuse(scope, send, 400, "bad request")
            return
        if is_denied(path):
            await self._refuse(scope, send, 403, "not available over the link")
            return
        if not is_public(path):
            cookie = read_cookie(scope)
            device = (self._pairing.device_for_cookie(cookie, host, self._hostname) if cookie else None)
            if device is None:
                await self._unpaired(scope, send)
                return
            stream.device = device
            self._pairing.touch(device)
            scope["link_device"] = device
            if not stream.trusted:
                stream.trusted = True
                self._send_trust(stream.stream_id)
        stream.request_seen = True
        await self.app(scope, receive, send)

    async def _unpaired(self, scope: Dict[str, Any], send: Send) -> None:
        if scope["type"] == "http" and scope.get("method") in ("GET", "HEAD"):
            await send({"type": "http.response.start", "status": 302, "headers": [
                (b"location", b"/pair"), (b"cache-control", b"no-store"), (b"content-length", b"0")]})
            await send({"type": "http.response.body", "body": b""})
            return
        await self._refuse(scope, send, 401, "pairing required")

    async def _refuse(self, scope: Dict[str, Any], send: Send, status: int, why: str) -> None:
        logger.warning("phone_link_gate_refused", status=status, why=why,
                       kind=scope["type"], path=repr(scope.get("path", "")[:64]))
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4000 + status % 1000})
            return
        payload = why.encode("ascii")
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"content-length", str(len(payload)).encode("ascii")),
            (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]})
        await send({"type": "http.response.body", "body": payload})

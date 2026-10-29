
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from src.core.mcp_health.fold import server_key

STDIO_GRACE: timedelta = timedelta(seconds=30)
TRANSPORT_STDIO: str = "stdio"
TRANSPORT_HTTP: str = "http"
TRANSPORT_SSE: str = "sse"
TRANSPORT_PROXY: str = "proxy"
TRANSPORT_UNKNOWN: str = "unknown"
REMOTE_TRANSPORTS: frozenset = frozenset({TRANSPORT_HTTP, TRANSPORT_SSE})

STATE_CONNECTED: str = "connected"
STATE_DOWN: str = "down"
STATE_NEEDS_AUTH: str = "needs_auth"
STATE_UNKNOWN: str = "unknown"
ALERT_STATES: frozenset = frozenset({STATE_DOWN, STATE_NEEDS_AUTH})

SOURCE_FIRST_HAND: str = "first_hand"
SOURCE_CLIENT_LOG: str = "client_log"
SOURCE_PROCESS: str = "process"
SOURCE_PROBE: str = "probe"
SOURCE_TRANSCRIPT: str = "transcript"

REASON_REFUSED: str = "refused"
REASON_DNS: str = "dns"
REASON_TIMEOUT: str = "timeout"
REASON_TLS: str = "tls"
REASON_UNREACHABLE: str = "unreachable"
REASON_SERVER_ERROR: str = "server_error"
REASON_NOT_FOUND: str = "not_found"
REASON_REACHABLE: str = "reachable"
REASON_AUTH_REQUIRED: str = "auth_required"
REASON_GAVE_UP: str = "gave_up"
REASON_CLOSED: str = "closed"
REASON_CONNECT_FAILED: str = "connect_failed"
REASON_NOT_IMPLEMENTED: str = "not_implemented"
REASON_RECONNECTING: str = "reconnecting"
REASON_PROCESS_GONE: str = "process_gone"
REASON_PROCESS_RUNNING: str = "process_running"
REASON_CONNECTED: str = "connected"
REASON_NEEDS_AUTH: str = "needs_auth"
REASON_NOT_SEEN: str = "not_seen"
REASON_TRANSCRIPT: str = "transcript"


@dataclass(frozen=True)
class ServerSpec:

    name: str
    transport: str
    url: Optional[str] = None
    command: Optional[str] = None
    args: Tuple[str, ...] = ()
    scope: str = ""

    @property
    def key(self) -> str:
        return server_key(self.name)


@dataclass(frozen=True)
class ServerHealth:

    name: str
    transport: str
    state: str
    reason: str
    source: str
    detail: Optional[str] = None
    at: Optional[datetime] = None
    exact: bool = True


def clean_url(raw: object) -> Optional[str]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parts = urlsplit(raw.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or "${" in parts.netloc:
        return None
    host = parts.hostname
    if ":" in host:
        host = "[" + host + "]"
    try:
        port = parts.port
    except ValueError:
        return None
    netloc = host + (f":{port}" if port else "")
    return urlunsplit((parts.scheme, netloc, parts.path or "/", "", ""))


def transport_of(entry: dict) -> str:
    kind = entry.get("type") or entry.get("transport")
    kind = kind.lower() if isinstance(kind, str) else ""
    if kind in ("http", "streamable-http", "streamable_http", "streamablehttp"):
        return TRANSPORT_HTTP
    if kind == "sse":
        return TRANSPORT_SSE
    if kind == "stdio":
        return TRANSPORT_STDIO
    if kind:
        return TRANSPORT_UNKNOWN
    if isinstance(entry.get("command"), str):
        return TRANSPORT_STDIO
    if isinstance(entry.get("url"), str):
        return TRANSPORT_HTTP
    return TRANSPORT_UNKNOWN


def spec_from_entry(name: str, entry: object, scope: str) -> Optional[ServerSpec]:
    if not isinstance(name, str) or not name.strip() or not isinstance(entry, dict):
        return None
    transport = transport_of(entry)
    command = entry.get("command") if isinstance(entry.get("command"), str) else None
    raw_args = entry.get("args")
    args = tuple(a for a in raw_args if isinstance(a, str)) if isinstance(raw_args, list) else ()
    url = clean_url(entry.get("url")) if transport in REMOTE_TRANSPORTS else None
    return ServerSpec(name=name, transport=transport, url=url, command=command, args=args, scope=scope)

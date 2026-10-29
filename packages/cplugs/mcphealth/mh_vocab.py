
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

TRANSPORT_STDIO, TRANSPORT_HTTP, TRANSPORT_SSE, TRANSPORT_PROXY, TRANSPORT_UNKNOWN = "stdio", "http", "sse", "proxy", "unknown"
STATE_CONNECTED, STATE_DOWN, STATE_NEEDS_AUTH, STATE_UNKNOWN = "connected", "down", "needs_auth", "unknown"
ALERT_STATES = frozenset({STATE_DOWN, STATE_NEEDS_AUTH})
SOURCE_CLIENT_LOG, SOURCE_PROCESS, SOURCE_PROBE = "client_log", "process", "probe"
REASON_CONNECTED, REASON_PROCESS_RUNNING, REASON_NOT_SEEN, REASON_PROCESS_GONE = "connected", "process_running", "not_seen", "process_gone"
REASON_NOT_IMPLEMENTED = "not_implemented"
REASON_NOT_FOUND = "not_found"
DROP_DROPPED, DROP_NEEDS_AUTH = "dropped", "needs_auth"

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def server_key(name: str) -> str:
    return _NON_ALNUM.sub("_", name.lower()).strip("_")


@dataclass(frozen=True)
class ServerSpec:

    name: str
    transport: str
    scope: str = ""
    command: Optional[str] = None
    alive: Optional[bool] = None

    @property
    def key(self) -> str:
        return server_key(self.name)


@dataclass(frozen=True)
class Link:

    name: str
    transport: str
    state: str
    reason: str

    @property
    def key(self) -> str:
        return server_key(self.name)


@dataclass(frozen=True)
class Health:

    name: str
    transport: str
    state: str
    reason: str
    source: str
    exact: bool = True

"""Carnivore's own reachability probe of remote MCP servers, shared per unique URL (#1678).

WHAT IT ANSWERS: is the endpoint up? NOT whether a session's client is connected to it: that is the session's
own link evidence (``client_log.py``, ``first_hand.py``), which outranks this. The probe EXPLAINS a down link
(refused, DNS, timeout) and catches an endpoint that is down right now while a quiet client still believes
it is connected.

WHAT IT SENDS: an unauthenticated MCP ``initialize`` POST (JSON-RPC, ``Accept: application/json,
text/event-stream``), the exact first request a client's connect makes, with NO credential of any session (no
Authorization, no configured header, no query string: ``servers.clean_url`` stripped it). Chosen over a bare
GET because a streamable-HTTP endpoint legitimately answers a GET with 405 or opens a stream, and a GET's 404
does not prove the POST route is missing; an initialize gets the answer the client's next connect would get,
minus credentials. Only the status line and headers are read, the body is never parsed. A server that mints a
session on it (``Mcp-Session-Id`` in the answer) gets the spec's ``DELETE`` for that id at once, so a probe leaves
nothing behind. An ``sse`` endpoint gets a ``GET`` with ``Accept: text/event-stream``, closed after the headers.

CLASSES: 2xx and every 4xx except the ones below are ``reachable``; 401/403 are ``auth_required`` (reachable,
sign-in not checked: the probe holds no credential, so this is never "down"); 404/410 are ``not_found`` (down,
the client's own ENDPOINT_NOT_FOUND); 5xx ``server_error`` (down); refused, DNS, timeout, TLS and other socket
errors are down with that reason.

COST: one request per unique URL per :data:`PROBE_INTERVAL` (60 s), at most :data:`MAX_CONCURRENT` at once,
each bounded by :data:`TIMEOUT` (5 s), on a worker thread pool, never the event loop. A URL no live session
names is forgotten.
"""

from __future__ import annotations

import http.client
import json
import socket
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, Optional, Tuple
from urllib.parse import urlsplit

import structlog

from src.core.mcp_health.servers import (
    REASON_AUTH_REQUIRED, REASON_DNS, REASON_NOT_FOUND, REASON_REACHABLE, REASON_REFUSED, REASON_SERVER_ERROR,
    REASON_TIMEOUT, REASON_TLS, REASON_UNREACHABLE, TRANSPORT_SSE,
)

log = structlog.get_logger()

PROBE_INTERVAL: timedelta = timedelta(seconds=60)
TIMEOUT: float = 5.0
MAX_CONCURRENT: int = 4
PROTOCOL_VERSION: str = "2025-06-18"
USER_AGENT: str = "carnivore-mcp-probe/1"
SESSION_HEADER: str = "Mcp-Session-Id"
_AUTH_STATUSES = frozenset({401, 403})
_NOT_FOUND_STATUSES = frozenset({404, 410})

_INITIALIZE = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
               "clientInfo": {"name": "carnivore-probe", "version": "1"}},
}).encode()


@dataclass(frozen=True)
class ProbeResult:

    reachable: bool
    reason: str
    detail: Optional[str]
    at: datetime


def classify_status(status: int) -> Tuple[bool, str]:
    if status in _AUTH_STATUSES:
        return True, REASON_AUTH_REQUIRED
    if status in _NOT_FOUND_STATUSES:
        return False, REASON_NOT_FOUND
    if status >= 500:
        return False, REASON_SERVER_ERROR
    return True, REASON_REACHABLE


def classify_error(exc: BaseException) -> Tuple[str, str]:
    if isinstance(exc, ConnectionRefusedError):
        return REASON_REFUSED, "ECONNREFUSED"
    if isinstance(exc, socket.gaierror):
        return REASON_DNS, "ENOTFOUND"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return REASON_TIMEOUT, "ETIMEDOUT"
    if isinstance(exc, ssl.SSLError):
        return REASON_TLS, "TLS"
    return REASON_UNREACHABLE, type(exc).__name__


def _connection(url: str, timeout: float) -> Tuple[http.client.HTTPConnection, str]:
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.scheme == "https":
        return http.client.HTTPSConnection(parts.hostname, parts.port, timeout=timeout,
                                           context=ssl.create_default_context()), path
    return http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout), path


def probe_once(url: str, transport: str, timeout: float = TIMEOUT, now: Optional[Callable[[], datetime]] = None) -> ProbeResult:
    clock = now or (lambda: datetime.now(timezone.utc))
    headers = {"User-Agent": USER_AGENT}
    try:
        conn, path = _connection(url, timeout)
    except (ValueError, http.client.InvalidURL) as exc:
        return ProbeResult(False, REASON_UNREACHABLE, type(exc).__name__, clock())
    try:
        if transport == TRANSPORT_SSE:
            headers["Accept"] = "text/event-stream"
            conn.request("GET", path, headers=headers)
        else:
            headers.update({"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                            "MCP-Protocol-Version": PROTOCOL_VERSION})
            conn.request("POST", path, body=_INITIALIZE, headers=headers)
        response = conn.getresponse()
        status = response.status
        minted = response.getheader(SESSION_HEADER)
        conn.close()
        if minted and 200 <= status < 300:
            _terminate(url, minted, timeout)
        reachable, reason = classify_status(status)
        return ProbeResult(reachable, reason, str(status), clock())
    except (OSError, http.client.HTTPException) as exc:
        reason, detail = classify_error(exc)
        return ProbeResult(False, reason, detail, clock())
    finally:
        conn.close()


def _terminate(url: str, session_id: str, timeout: float) -> None:
    if not session_id.isprintable() or len(session_id) > 512:
        return
    try:
        conn, path = _connection(url, timeout)
        conn.request("DELETE", path, headers={"User-Agent": USER_AGENT, SESSION_HEADER: session_id,
                                              "MCP-Protocol-Version": PROTOCOL_VERSION})
        conn.getresponse()
        conn.close()
    except (OSError, http.client.HTTPException, ValueError) as exc:
        log.debug("mcp_probe_terminate_failed", error=type(exc).__name__)


class ProbeTable:

    def __init__(self, probe: Callable[[str, str], ProbeResult] = probe_once,
                 interval: timedelta = PROBE_INTERVAL, max_concurrent: int = MAX_CONCURRENT) -> None:
        self._probe = probe
        self._interval = interval
        self._pool = ThreadPoolExecutor(max_workers=max_concurrent, thread_name_prefix="mcp-probe")
        self._results: Dict[Tuple[str, str], ProbeResult] = {}
        self._lock = threading.Lock()

    def due(self, wanted: Iterable[Tuple[str, str]], now: datetime) -> Tuple[Tuple[str, str], ...]:
        keys = set(wanted)
        with self._lock:
            for stale in [k for k in self._results if k not in keys]:
                del self._results[stale]
            return tuple(k for k in sorted(keys) if k not in self._results
                         or now - self._results[k].at >= self._interval)

    def refresh(self, wanted: Iterable[Tuple[str, str]], now: datetime) -> bool:
        due = self.due(wanted, now)
        if not due:
            return False
        answers = list(self._pool.map(lambda key: (key, self._probe(key[1], key[0])), due))
        changed = False
        with self._lock:
            for key, result in answers:
                old = self._results.get(key)
                changed = changed or old is None or (old.reachable, old.reason) != (result.reachable, result.reason)
                self._results[key] = result
        return changed

    def get(self, transport: str, url: Optional[str]) -> Optional[ProbeResult]:
        if not url:
            return None
        with self._lock:
            return self._results.get((transport, url))

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

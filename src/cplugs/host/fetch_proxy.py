
from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable, Collection, Deque, Dict, List, Mapping, Optional, Set, Tuple
from urllib.parse import urljoin

import structlog

from src.cplugs.host import netguard
from src.cplugs.host.egress_log import EgressLog
from src.cplugs.host.fetch_transport import RawResponse, StdlibTransport, Transport
from src.cplugs.host.netguard import Refused, Target
from src.cplugs.host.secret_store import SecretStore
from src.cplugs.sdk.manifest import Manifest
from src.cplugs.sdk.network import FORBIDDEN_HEADER_PREFIXES, FORBIDDEN_HEADERS, READ_METHODS, WRITE_METHODS, literal_kind

logger = structlog.get_logger()

MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
TOTAL_TIMEOUT_S = 15.0
MAX_REDIRECTS = 3
RATE_PER_MINUTE = 30
PER_PLUGIN_CONCURRENCY = 4
_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="cplug-fetch")
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_CROSS_HOST_KEEP = frozenset({"accept", "accept-language", "content-type"})
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_DROP_RESPONSE = frozenset({"set-cookie", "set-cookie2", "www-authenticate", "proxy-authenticate", "connection", "transfer-encoding"})


class FetchRefused(Exception):

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class FetchResponse:

    status: int
    headers: Dict[str, str]
    body: bytes
    truncated: bool = False


@dataclass(frozen=True)
class _Route:

    kind: str
    entry: Any
    permission: str


class RateLimiter:

    def __init__(self, per_minute: int = RATE_PER_MINUTE, clock: Callable[[], float] = time.monotonic) -> None:
        self._cap, self._clock = per_minute, clock
        self._hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, cplug_id: str, host: str) -> bool:
        now = self._clock()
        with self._lock:
            window = self._hits[(cplug_id, host)]
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) >= self._cap:
                return False
            window.append(now)
            return True


class PluginFetch:

    def __init__(self, manifest: Manifest, key: str, granted: Callable[[], Collection[str]], secrets: SecretStore, log: EgressLog,
                 limiter: RateLimiter, *, peers: Callable[[], netguard.Peers] = netguard.peer_addresses,
                 resolver: Callable[[str, int], List[str]] = netguard.resolve,
                 transport: Optional[Transport] = None, is_own: Callable[[str], bool] = netguard.is_own_address,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._m, self._key, self._grants = manifest, key, granted
        self._slots = asyncio.Semaphore(PER_PLUGIN_CONCURRENCY)
        self._secrets, self._log, self._limiter = secrets, log, limiter
        self._peers, self._resolve, self._is_own, self._clock = peers, resolver, is_own, clock
        self._transport: Transport = transport or StdlibTransport()

    def _match(self, t: Target, granted: Collection[str]) -> _Route:
        for lan in self._m.network.lan_hosts:
            if lan.permission in granted and (lan.scheme, lan.host, lan.port) == (t.scheme, t.host, t.port):
                return _Route("lan", lan, lan.permission)
        if literal_kind(t.host) is not None:
            raise Refused("ip_literal", "an IP literal needs a lan_hosts entry naming it")
        if t.scheme != "https":
            raise Refused("scheme_refused", "only https (and http to a granted LAN entry)")
        if t.port != 443:
            raise Refused("port_refused", "only port 443 (a LAN entry names its own port)")
        for host in self._m.network.network_hosts:
            if host.host == t.host and host.permission in granted:
                return _Route("network", host, host.permission)
        raise Refused("permission_denied", f"no granted network_hosts entry for {t.host}")

    def _check_method(self, route: _Route, method: str, t: Target, granted: Collection[str]) -> None:
        entry = route.entry
        if method not in READ_METHODS + WRITE_METHODS or method not in entry.methods:
            raise Refused("method_refused", f"{method} is not declared for {t.host}")
        if method in WRITE_METHODS and entry.write_permission not in granted:
            raise Refused("write_not_granted", f"can send data to {t.host}: that tick is not granted")
        if not netguard.path_allowed(t.path, entry.paths):
            raise Refused("path_refused", "the path is outside the declared prefixes")

    @staticmethod
    def _clean_headers(raw: Optional[Mapping[str, str]], drop: Optional[str], keep_only: Optional[frozenset]) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        for name, value in (raw or {}).items():
            if not isinstance(name, str) or not isinstance(value, str) or not _HEADER_NAME.match(name) or re.search(r"[\r\n\x00]", value):
                raise Refused("bad_header", "a header name or value is not allowed")
            low = name.lower()
            if (low in FORBIDDEN_HEADERS or low.startswith(FORBIDDEN_HEADER_PREFIXES) or low == (drop or "").lower()
                    or (keep_only is not None and low not in keep_only)):
                continue
            out.append((name, value))
        return out

    @staticmethod
    def _scan(headers: List[Tuple[str, str]], t: Target, body: Optional[bytes]) -> None:
        from src.core.message_model_secrets import scan_text  # noqa: PLC0415

        pieces = [f"{n}: {v}" for n, v in headers] + [t.query, t.path]
        if body:
            pieces.append(body.decode("utf-8", "replace"))
        for piece in pieces:
            found = scan_text(piece, trust_vendor_marker=True)
            if found:
                raise Refused("secret_in_request", f"detector {found[0].detector}")

    async def fetch(self, method: str, url: str, *, headers: Optional[Mapping[str, str]] = None,
                    body: Optional[bytes] = None) -> FetchResponse:
        async with self._slots:
            return await asyncio.get_running_loop().run_in_executor(
                _POOL, lambda: self.fetch_blocking(method, url, headers=headers, body=body))

    def fetch_blocking(self, method: str, url: str, *, headers: Optional[Mapping[str, str]] = None,
                       body: Optional[bytes] = None) -> FetchResponse:
        method = method.upper() if isinstance(method, str) else ""
        if body is not None and (not isinstance(body, (bytes, bytearray)) or len(body) > MAX_REQUEST_BYTES):
            self._refuse(url, method, "request_too_large", 0)
        if body is not None and method not in WRITE_METHODS:
            self._refuse(url, method, "body_not_allowed", 0)
        deadline = self._clock() + TOTAL_TIMEOUT_S
        body_out = bytes(body) if body is not None else None
        plugin_headers: Optional[Mapping[str, str]] = headers
        cur_url, cur_method = url, method
        for hop in range(MAX_REDIRECTS + 1):
            if self._clock() > deadline:
                self._refuse(cur_url, cur_method, "timeout", 0)
            resp, t, secret_value = self._hop(cur_method, cur_url, plugin_headers, body_out, deadline)
            location = next((v for n, v in resp.headers if n.lower() == "location"), None)
            if resp.status not in _REDIRECTS or not location:
                return self._finish(resp, secret_value)
            if hop == MAX_REDIRECTS:
                self._refuse(cur_url, cur_method, "too_many_redirects", 0)
            nxt = urljoin(cur_url, location)
            try:
                cross_host = netguard.parse_target(nxt).host != t.host
            except Refused as exc:
                self._refuse(cur_url, cur_method, exc.code, 0)
            if cross_host:
                plugin_headers = dict(self._clean_headers(plugin_headers, None, _CROSS_HOST_KEEP))
            if resp.status in (301, 302, 303) and cur_method not in READ_METHODS:
                cur_method, body_out = "GET", None
            cur_url = nxt
        raise AssertionError("unreachable")

    def _refuse(self, url: str, method: str, code: str, started_ms: int, host: Optional[str] = None, permission: str = "") -> None:
        if host is None:
            try:
                host = netguard.parse_target(url).host
            except Refused:
                host = ""
        self._log.record(self._key, host=host, method=method, permission=permission, status=0, bytes_out=0, bytes_in=0,
                         ms=started_ms, outcome=code)
        logger.info("cplug_fetch_refused", cplug=self._m.id, host=host, method=method, code=code)
        raise FetchRefused(code)

    def _hop(self, method: str, url: str, headers: Optional[Mapping[str, str]], body: Optional[bytes], deadline: float,
             ) -> Tuple[RawResponse, Target, Optional[str]]:
        started = self._clock()
        host, permission = "", ""
        try:
            t = netguard.parse_target(url)
            host = t.host
            granted = frozenset(self._grants())
            route = self._match(t, granted)
            permission = route.permission
            self._check_method(route, method, t, granted)
            auth = route.entry.auth if route.kind == "network" else None
            clean = self._clean_headers(headers, auth.header if auth else None, None)
            self._scan(clean, t, body)
            peers = self._peers()
            if route.kind == "lan" and not peers.complete:
                raise Refused("peers_unknown", "the paired peers' addresses could not all be found")
            want = netguard.PRIVATE if route.kind == "lan" else netguard.PUBLIC
            ip = netguard.check_resolution(self._resolve(t.host, t.port), want, peers.addresses, self._is_own)
            value = None
            if auth is not None:
                value = self._secrets.value_for(self._key, self._m, auth.secret, t.host)
                if value is None:
                    raise Refused("secret_missing", f"{auth.secret} is not stored for {t.host}")
                clean.append((auth.header, f"{auth.scheme} {value}".strip()))
            if not self._limiter.allow(self._m.id, t.host):
                raise Refused("rate_limited", f"more than {RATE_PER_MINUTE} requests a minute to {t.host}")
        except Refused as exc:
            self._refuse(url, method, exc.code, int((self._clock() - started) * 1000), host, permission)
        clean.append(("User-Agent", f"carnivore-cplug/{self._m.id}"))
        clean.append(("Connection", "close"))
        target = t.path + (f"?{t.query}" if t.query else "")
        try:
            raw = self._transport.send(ip=ip, port=t.port, tls=t.scheme == "https", host=t.host, method=method, target=target,
                                       headers=clean, body=body, deadline=deadline, max_bytes=MAX_RESPONSE_BYTES)
        except TimeoutError:
            self._refuse(url, method, "timeout", int((self._clock() - started) * 1000), host, permission)
        except Exception as exc:  # noqa: BLE001
            logger.info("cplug_fetch_upstream_error", cplug=self._m.id, host=host, error_type=type(exc).__name__)
            self._refuse(url, method, "upstream_error", int((self._clock() - started) * 1000), host, permission)
        echo = value is not None and (value.encode() in raw.body or any(value in v for _, v in raw.headers))
        self._log.record(self._key, host=host, method=method, permission=permission, status=raw.status,
                         bytes_out=len(body or b""), bytes_in=len(raw.body), ms=int((self._clock() - started) * 1000),
                         outcome="credential_echo" if echo else "ok")
        return raw, t, value

    @staticmethod
    def _finish(raw: RawResponse, secret_value: Optional[str]) -> FetchResponse:
        headers: Dict[str, str] = {}
        for name, value in raw.headers:
            low = name.lower()
            if low in _DROP_RESPONSE or (secret_value and secret_value in value):
                continue
            headers[low] = value
        body = raw.body.replace(secret_value.encode(), b"[redacted]") if secret_value else raw.body
        return FetchResponse(raw.status, headers, body, raw.truncated)


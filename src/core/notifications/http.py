
from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import re
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional

import httpcore
import httpx
import structlog

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

log = structlog.get_logger(__name__)

MAX_BODY_BYTES = 64 * 1024

Resolver = Callable[[str, int], Awaitable[list[str]]]
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class GuardError(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class GuardBlocked(GuardError):
    pass


class GuardLocalPolicy(GuardBlocked):

    def __init__(self, reason: str, switch: str) -> None:
        super().__init__(reason)
        self.switch = switch


class GuardTimeout(GuardError):
    pass


class GuardNetworkError(GuardError):
    pass


@dataclass(frozen=True)
class HostPolicy:

    exact: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    pattern: Optional[str] = None
    any_host: bool = False
    allow_private: bool = False
    allow_plain_http: bool = False
    switchable: bool = False
    origin_changed: bool = False


@dataclass(frozen=True)
class GuardResponse:

    status: int
    headers: Mapping[str, str]
    body: bytes
    truncated: bool


def normalize_host(host: str) -> str:
    h = host.strip().lower().rstrip(".")
    if not h:
        raise GuardBlocked("host")
    try:
        return h.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise GuardBlocked("host") from exc


def host_allowed(host: str, policy: HostPolicy) -> bool:
    if policy.any_host:
        return True
    if host in {normalize_host(e) for e in policy.exact}:
        return True
    for suffix in policy.suffixes:
        s = "." + normalize_host(suffix.lstrip("."))
        if host.endswith(s) and len(host) > len(s):
            return True
    return bool(policy.pattern and re.fullmatch(policy.pattern, host))


def _embedded_v4(ip: ipaddress.IPv6Address) -> Optional[ipaddress.IPv4Address]:
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    packed = ip.packed
    if ip in ipaddress.ip_network("::/96"):
        return ipaddress.IPv4Address(packed[12:])
    if ip in ipaddress.ip_network("64:ff9b::/96"):
        return ipaddress.IPv4Address(packed[12:])
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        server, client = ip.teredo
        return client if client.is_global else server
    return None


_METADATA: frozenset = frozenset(ipaddress.ip_address(a) for a in ("fd00:ec2::254", "100.100.100.200", "192.0.0.192"))


def ip_literal(host: str) -> Optional[IPAddress]:
    text = host.strip("[]")
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(text))
    except (OSError, ValueError):
        return None


def origin_of(url: str) -> Optional[str]:
    try:
        u, host, port = _parse(url)
    except GuardError:
        return None
    return f"{u.scheme}://{'[' + host + ']' if ':' in host else host}:{port}"


def address_verdict(ip: IPAddress, *, allow_private: bool) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        inner = _embedded_v4(ip)
        if inner is not None:
            return address_verdict(inner, allow_private=allow_private)
    if ip.is_global and not ip.is_multicast:
        return True
    if ip.is_unspecified or ip.is_multicast or ip.is_link_local or ip.is_reserved or ip in _METADATA:
        return False
    return allow_private


async def _system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise GuardNetworkError("dns") from exc
    out: list[str] = []
    for info in infos:
        addr = info[4][0]
        if addr not in out:
            out.append(addr)
    return out


class _PinnedBackend(httpcore.AsyncNetworkBackend):

    def __init__(self, ip: str, inner: httpcore.AsyncNetworkBackend) -> None:
        self._ip = ip
        self._inner = inner

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return await self._inner.connect_tcp(
            self._ip, port, timeout=timeout, local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise GuardBlocked("address")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


_ssl_context: Optional[ssl.SSLContext] = None


def _default_ssl_context() -> ssl.SSLContext:
    global _ssl_context
    if _ssl_context is None:
        _ssl_context = httpx.create_ssl_context(verify=True, trust_env=False)
    return _ssl_context


def _block(dest_id: str, host: str, exc: GuardBlocked) -> GuardBlocked:
    log.warning("guarded_http.blocked", dest_id=dest_id, host=host, reason=exc.reason)
    return exc


def _parse(url: str) -> tuple[httpx.URL, str, int]:
    if "\\" in url:
        raise GuardBlocked("url")
    try:
        u = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise GuardBlocked("url") from exc
    if u.scheme not in ("https", "http"):
        raise GuardBlocked("scheme")
    if u.userinfo or "@" in u.netloc.decode("ascii", "ignore"):
        raise GuardBlocked("userinfo")
    host = normalize_host(u.raw_host.decode("ascii"))
    return u.copy_with(host=host), host, u.port or (80 if u.scheme == "http" else 443)


@dataclass(frozen=True)
class VettedTarget:

    url: httpx.URL
    host: str
    port: int
    addrs: tuple[str, ...]


async def vet_target(url: str, *, policy: HostPolicy, timeout: float = 10.0,
                     resolver: Optional[Resolver] = None) -> VettedTarget:
    u, host, port = _parse(url)
    if not host_allowed(host, policy):
        raise GuardBlocked("host")
    plain = u.scheme == "http"
    if plain and not policy.switchable:
        raise GuardBlocked("scheme")
    literal = ip_literal(host)
    if literal is not None:
        addrs = [str(literal)]
    else:
        try:
            async with asyncio.timeout(timeout):
                addrs = await (resolver or _system_resolver)(host, port)
        except TimeoutError as exc:
            raise GuardTimeout("timeout") from exc
    if not addrs:
        raise GuardNetworkError("dns")
    pending: Optional[tuple[str, str]] = None
    if plain and not policy.allow_plain_http:
        pending = ("scheme", "plain_http")
    elif plain and not policy.allow_private:
        pending = ("scheme", "private")
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError as exc:
            raise GuardBlocked("address") from exc
        if plain and address_verdict(ip, allow_private=False):
            raise GuardBlocked("address")
        if not address_verdict(ip, allow_private=True):
            raise GuardBlocked("address")
        if not address_verdict(ip, allow_private=policy.allow_private):
            if not policy.switchable:
                raise GuardBlocked("address")
            pending = pending or ("address", "private")
    if pending:
        raise GuardLocalPolicy(pending[0], "origin" if policy.origin_changed else pending[1])
    return VettedTarget(u, host, port, tuple(addrs))


async def guarded_request(
    method: str,
    url: str,
    *,
    policy: HostPolicy,
    dest_id: str,
    headers: Optional[Mapping[str, str]] = None,
    json: Any = None,
    data: Optional[Mapping[str, Any]] = None,
    content: Optional[bytes] = None,
    auth: Optional[tuple[str, str]] = None,
    timeout: float = 10.0,
    resolver: Optional[Resolver] = None,
    network_backend: Optional[httpcore.AsyncNetworkBackend] = None,
) -> GuardResponse:
    start = time.monotonic()
    host = ""
    try:
        host = _parse(url)[1]
    except GuardBlocked:
        pass
    try:
        target = await vet_target(url, policy=policy, timeout=timeout, resolver=resolver)
        u, host, addrs = target.url, target.host, target.addrs
        resp = await _send(
            method, u, addrs[0], dict(headers or {}), json, data, content, auth,
            timeout, network_backend,
        )
    except GuardBlocked as exc:
        raise _block(dest_id, host, exc) from exc
    except GuardError as exc:
        log.warning("guarded_http.failed", dest_id=dest_id, host=host, reason=exc.reason,
                    elapsed_ms=int((time.monotonic() - start) * 1000))
        raise
    log.info("guarded_http.response", dest_id=dest_id, host=host, status=resp.status,
             elapsed_ms=int((time.monotonic() - start) * 1000))
    return resp


async def _send(
    method: str, u: httpx.URL, pinned_ip: str, headers: dict[str, str], json: Any,
    data: Optional[Mapping[str, Any]], content: Optional[bytes],
    auth: Optional[tuple[str, str]], timeout: float,
    backend: Optional[httpcore.AsyncNetworkBackend],
) -> GuardResponse:
    req = httpx.Request(method, u, headers=headers, json=json, data=data, content=content)
    body_in = await req.aread()
    hdrs = [(k, v) for k, v in req.headers.raw if k.lower() != b"user-agent"]
    hdrs.append((b"user-agent", b"carnivore-notify"))
    hdrs.append((b"accept-encoding", b"identity"))
    if auth is not None:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode("utf-8")).decode("ascii")
        hdrs.append((b"authorization", f"Basic {token}".encode("ascii")))
    inner = backend or httpcore.AnyIOBackend()
    pool = httpcore.AsyncConnectionPool(
        ssl_context=_default_ssl_context(), max_connections=1, retries=0,
        http1=True, http2=False, network_backend=_PinnedBackend(pinned_ip, inner),
    )
    try:
        async with asyncio.timeout(timeout):
            async with pool.stream(
                method, httpcore.URL(scheme=u.scheme, host=u.raw_host, port=u.port, target=u.raw_path),
                headers=hdrs, content=body_in, extensions={"timeout": {
                    "connect": timeout, "read": timeout, "write": timeout, "pool": timeout}},
            ) as r:
                if 300 <= r.status < 400:
                    raise GuardBlocked("redirect")
                buf = bytearray()
                truncated = False
                async for chunk in r.aiter_stream():
                    buf += chunk
                    if len(buf) > MAX_BODY_BYTES:
                        truncated = True
                        del buf[MAX_BODY_BYTES:]
                        break
                out_headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in r.headers}
                return GuardResponse(r.status, out_headers, bytes(buf), truncated)
    except TimeoutError as exc:
        raise GuardTimeout("timeout") from exc
    except httpcore.TimeoutException as exc:
        raise GuardTimeout("timeout") from exc
    except (httpcore.NetworkError, httpcore.ProtocolError, ssl.SSLError, OSError) as exc:
        raise GuardNetworkError(type(exc).__name__.lower()) from exc
    finally:
        await pool.aclose()

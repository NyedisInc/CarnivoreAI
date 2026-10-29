
from __future__ import annotations

import ipaddress
import posixpath
import socket
import sqlite3
import subprocess
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from typing import Callable, Iterable, List, Set
from urllib.parse import unquote, urlsplit

import structlog

from src.cplugs.sdk.network import normalize_host

logger = structlog.get_logger()

NEVER, PRIVATE, PUBLIC = "never", "private", "public"
_METADATA = frozenset({ipaddress.ip_address("fd00:ec2::254"), ipaddress.ip_address("100.100.100.200")})
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_SIXTO4 = ipaddress.ip_network("2002::/16")
_MAX_URL = 4096


class Refused(Exception):

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class Target:

    scheme: str
    host: str
    port: int
    path: str
    query: str


def parse_target(url: str) -> Target:
    if not isinstance(url, str) or len(url) > _MAX_URL or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise Refused("bad_url", "control characters or whitespace")
    try:
        parts = urlsplit(url)
        port = parts.port
        raw_host = parts.hostname or ""
    except ValueError as exc:
        raise Refused("bad_url", "unparseable") from exc
    if parts.scheme not in ("http", "https"):
        raise Refused("scheme_refused", "only https (and http to a granted LAN entry)")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise Refused("userinfo_refused", "credentials in a URL")
    try:
        host = normalize_host(raw_host)
    except ValueError as exc:
        raise Refused("bad_url", "bad host") from exc
    return Target(parts.scheme, host, port or (443 if parts.scheme == "https" else 80), parts.path or "/", parts.query)


def path_allowed(path: str, prefixes: Iterable[str]) -> bool:
    decoded = unquote(unquote(path))
    if "\\" in decoded or any(seg in ("..", ".") for seg in decoded.split("/")):
        return False
    clean = posixpath.normpath(decoded)
    clean = "/" + clean.lstrip("/")
    for prefix in prefixes:
        base = prefix.rstrip("/")
        if not base or clean == base or clean.startswith(base + "/"):
            return True
    return False


def _embedded_v4(ip: ipaddress.IPv6Address) -> List[ipaddress.IPv4Address]:
    out: List[ipaddress.IPv4Address] = []
    if ip.ipv4_mapped is not None:
        out.append(ip.ipv4_mapped)
    packed = ip.packed
    if ip in _NAT64:
        out.append(ipaddress.IPv4Address(packed[12:]))
    if ip in _SIXTO4:
        out.append(ipaddress.IPv4Address(packed[2:6]))
    if packed[:12] == bytes(12) and int.from_bytes(packed[12:], "big") > 1:
        out.append(ipaddress.IPv4Address(packed[12:]))
    return out


def is_own_address(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    family = socket.AF_INET6 if addr.version == 6 else socket.AF_INET
    try:
        with closing(socket.socket(family, socket.SOCK_STREAM)) as probe:
            probe.bind((ip, 0))
    except OSError:
        return False
    return True


def classify(ip: str, peers: Set[str], is_own: Callable[[str], bool] = is_own_address) -> str:
    addr = ipaddress.ip_address(ip)
    seen: List[ipaddress._BaseAddress] = [addr]
    if addr.version == 6:
        seen += _embedded_v4(addr)
    for a in seen:
        if (a.is_loopback or a.is_link_local or a.is_unspecified or a in _METADATA
                or str(a) in peers or is_own(str(a))):
            return NEVER
    return PUBLIC if all(a.is_global for a in seen) else PRIVATE


def resolve(host: str, port: int) -> List[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError) as exc:
        raise Refused("dns_failed", type(exc).__name__) from exc
    out: List[str] = []
    for info in infos:
        ip = str(ipaddress.ip_address(info[4][0].split("%", 1)[0]))
        if ip not in out:
            out.append(ip)
    if not out:
        raise Refused("dns_failed", "no address")
    return out


@dataclass(frozen=True)
class Peers:

    addresses: Set[str]
    complete: bool = True


_PEER_TTL_S = 30.0
_peer_cache: List[object] = []
_peer_lock = threading.Lock()


def ssh_hostname(target: str) -> str:
    if target.startswith("-"):
        raise ValueError("option-like target")
    out = subprocess.run(["ssh", "-G", "--", target], capture_output=True, text=True, timeout=3, check=True).stdout
    for line in out.splitlines():
        if line.startswith("hostname "):
            return line.split(None, 1)[1].strip().strip("[]")
    raise ValueError("no hostname")


def peer_addresses(resolver: Callable[[str, int], List[str]] = resolve, hostname: Callable[[str], str] = ssh_hostname,
                   clock: Callable[[], float] = time.monotonic) -> Peers:
    now = clock()
    with _peer_lock:
        if _peer_cache and now < _peer_cache[0]:  # type: ignore[operator]
            return _peer_cache[1]  # type: ignore[return-value]
    from src.api.peer_auth import open_db  # noqa: PLC0415
    from src.core.federation import peer_hosts  # noqa: PLC0415

    try:
        with closing(open_db()) as conn:
            targets = [p.ssh_target for p in peer_hosts.list_peers(conn) if p.ssh_target]
    except (sqlite3.Error, OSError) as exc:
        logger.warning("cplug_peer_addresses_unreadable", error_type=type(exc).__name__)
        return Peers(set(), False)
    out: Set[str] = set()
    complete = True
    for target in targets:
        names = {target.rsplit("@", 1)[-1].strip("[]")}
        try:
            names.add(hostname(target))
        except (OSError, subprocess.SubprocessError, ValueError):
            complete = False
        resolved = False
        for name in names:
            try:
                out.update(resolver(name, 22))
                resolved = True
            except Refused:
                continue
        complete = complete and resolved
    result = Peers(out, complete)
    with _peer_lock:
        _peer_cache[:] = [now + _PEER_TTL_S, result]
    return result


def check_resolution(addresses: List[str], want: str, peers: Set[str],
                     is_own: Callable[[str], bool] = is_own_address) -> str:
    classes = [classify(a, peers, is_own) for a in addresses]
    if NEVER in classes:
        raise Refused("address_never", "loopback, link-local, this computer or a paired peer")
    if want == PUBLIC and PRIVATE in classes:
        raise Refused("private_address", "the host resolves to a private address and no lan_hosts entry covers it")
    if want == PRIVATE and PUBLIC in classes:
        raise Refused("address_not_private", "the LAN entry resolves to a public address")
    return addresses[0]

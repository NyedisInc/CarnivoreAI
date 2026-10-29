
from __future__ import annotations

import ipaddress
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Request

from src.api.host_guard import split_host_port
from src.config import settings
from src.core.phone_link.gate import STRIPPED_HEADERS
from src.core.product_identity import env_value
from src.core.setup_state import current_setup_state

FORWARDING_HEADERS: tuple[str, ...] = tuple(h.decode("ascii") for h in STRIPPED_HEADERS)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_loopback_host(host: Optional[str]) -> bool:
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def paired_state() -> Optional[bool]:
    for check in current_setup_state().checks:
        if check.key == "totp_paired":
            return check.passed
    return None


def repair_hatch_open() -> bool:
    return env_value("ALLOW_QR_REPAIR") == "1"


def _raw_headers(request: Request, name: bytes) -> list[str]:
    return [v.decode("latin-1") for k, v in request.scope.get("headers", []) if k.lower() == name]


def _origin_matches(origin: str, host: str, port: int) -> bool:
    try:
        parts = urlsplit(origin)
        origin_port = parts.port
    except ValueError:
        return False
    if parts.scheme != "http" or parts.username is not None or parts.password is not None:
        return False
    if parts.path or parts.query or parts.fragment:
        return False
    return (parts.hostname or "").lower() == host and origin_port == port


def is_local_request(request: Request) -> bool:
    scope = request.scope
    if scope.get("via_link") or scope.get("via_peer_link"):
        return False
    client = request.client
    if client is None or not is_loopback_host(client.host):
        return False
    server = scope.get("server")
    if not server or len(server) < 2 or server[1] != settings.port:
        return False
    names = {k.decode("latin-1").lower() for k, _ in scope.get("headers", [])}
    if any(n in FORWARDING_HEADERS or n.startswith("tailscale-") for n in names):
        return False
    hosts = _raw_headers(request, b"host")
    if len(hosts) != 1:
        return False
    split = split_host_port(hosts[0])
    if split is None:
        return False
    host, port = split
    if host not in _LOOPBACK_HOSTS or port != settings.port:
        return False
    for origin in _raw_headers(request, b"origin"):
        if not _origin_matches(origin.strip(), host, port):
            return False
    for site in _raw_headers(request, b"sec-fetch-site"):
        if site.strip().lower() not in ("same-origin", "none"):
            return False
    return True


def is_local_transport(request: Request) -> bool:
    return is_local_request(request) and b"authorization" not in {
        k.lower() for k, _ in request.scope.get("headers", [])
    }


def is_local_enrollment(request: Request) -> bool:
    state = paired_state()
    if state is None or (state and not repair_hatch_open()):
        return False
    return is_local_transport(request)

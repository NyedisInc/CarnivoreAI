
from __future__ import annotations

import ipaddress
from typing import Iterable, Optional, Union

import structlog

from src.config import settings

logger = structlog.get_logger()

FIELD = "trusted_proxy_hosts"

MAX_HOSTS = 8

IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]


class TrustedProxyError(ValueError):
    pass


def normalize(host: Optional[str]) -> Optional[IPAddress]:
    try:
        ip = ipaddress.ip_address((host or "").strip())
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def validate_entry(value: str) -> str:
    ip = normalize(value) if isinstance(value, str) else None
    if ip is None:
        raise TrustedProxyError(f"not an ip address: {str(value)[:64]!r}")
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        raise TrustedProxyError(f"not allowed as a trusted proxy: {ip}")
    return str(ip)


def validate_list(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        canonical = validate_entry(value)
        if canonical not in out:
            out.append(canonical)
    if len(out) > MAX_HOSTS:
        raise TrustedProxyError(f"at most {MAX_HOSTS} addresses")
    return out


def configured() -> list[str]:
    try:
        values = settings.load_auth_config().mcp.trusted_proxy_hosts
    except (ValueError, OSError) as exc:
        logger.warning("mcp_trusted_proxy_config_unreadable", error=type(exc).__name__)
        return []
    return list(values or [])


def is_trusted(host: Optional[str], hosts: Optional[Iterable[str]] = None) -> bool:
    peer = normalize(host)
    if peer is None or peer.is_loopback:
        return False
    for entry in configured() if hosts is None else hosts:
        try:
            if normalize(validate_entry(entry)) == peer:
                return True
        except TrustedProxyError:
            continue
    return False

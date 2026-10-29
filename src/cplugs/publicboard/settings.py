
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any, List, Mapping, Tuple

from src.cplugs.sdk import SettingsVerdict

KEY_PORT, KEY_BIND, KEY_HOSTS, KEY_PROXIES = "port", "bindAddress", "hostnames", "trustedProxies"
DEFAULT_PORT = 8190
DEFAULT_BIND = "127.0.0.1"
RESERVED_PORTS = frozenset({5000, 8000})
MIN_PORT, MAX_PORT = 1024, 65535
_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)
MAX_HOSTNAME = 253


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class PublicBoardSettings:

    port: int
    bind: str
    hostnames: Tuple[str, ...]
    trusted_proxies: Tuple[str, ...]

    @property
    def configured(self) -> bool:
        return bool(self.hostnames) and bool(self.trusted_proxies)


def _items(text: Any, key: str) -> List[str]:
    if not isinstance(text, str):
        raise SettingsError(f"{key} must be a comma-separated list")
    return [part.strip() for part in text.split(",") if part.strip()]


def parse_port(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise SettingsError(f"{KEY_PORT} must be a whole number")
    port = int(value)
    if not MIN_PORT <= port <= MAX_PORT or port in RESERVED_PORTS:
        raise SettingsError(f"{KEY_PORT} must be {MIN_PORT} to {MAX_PORT}, and not {sorted(RESERVED_PORTS)}")
    return port


def parse_bind(value: Any) -> str:
    try:
        address = ipaddress.ip_address(value.strip() if isinstance(value, str) else value)
    except ValueError as exc:
        raise SettingsError(f"{KEY_BIND} must be an IP address") from exc
    if address.is_unspecified or address.is_multicast:
        raise SettingsError(f"{KEY_BIND} must be one specific interface, not every interface")
    return str(address)


def parse_hostnames(value: Any) -> Tuple[str, ...]:
    names: List[str] = []
    for name in _items(value, KEY_HOSTS):
        labels = name.split(".")
        if len(name) > MAX_HOSTNAME or not all(_LABEL.fullmatch(label) for label in labels):
            raise SettingsError(f"{KEY_HOSTS}: {name!r} is not a lowercase host name (no port, no trailing dot, no wildcard)")
        if _is_ip(name) or labels[-1].isdigit():
            raise SettingsError(f"{KEY_HOSTS}: {name!r} is an IP address; a host name is required")
        if name not in names:
            names.append(name)
    return tuple(names)


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def parse_proxies(value: Any) -> Tuple[str, ...]:
    peers: List[str] = []
    for entry in _items(value, KEY_PROXIES):
        try:
            address = ipaddress.ip_address(entry)
        except ValueError as exc:
            raise SettingsError(f"{KEY_PROXIES}: {entry!r} is not an exact IP address (no ranges, no names)") from exc
        if address.is_loopback or address.is_unspecified or address.is_multicast:
            raise SettingsError(f"{KEY_PROXIES}: {entry!r} cannot be a trusted proxy")
        canon = str(getattr(address, "ipv4_mapped", None) or address)
        if canon not in peers:
            peers.append(canon)
    return tuple(peers)


def parse_settings(raw: Mapping[str, Any]) -> PublicBoardSettings:
    return PublicBoardSettings(
        port=parse_port(raw.get(KEY_PORT, DEFAULT_PORT)), bind=parse_bind(raw.get(KEY_BIND, DEFAULT_BIND)),
        hostnames=parse_hostnames(raw.get(KEY_HOSTS, "")), trusted_proxies=parse_proxies(raw.get(KEY_PROXIES, "")))


_PARSERS = {KEY_PORT: parse_port, KEY_BIND: parse_bind, KEY_HOSTS: parse_hostnames, KEY_PROXIES: parse_proxies}


def check_settings(changes: Mapping[str, Any]) -> SettingsVerdict:
    for key, parser in _PARSERS.items():
        if key in changes:
            try:
                parser(changes[key])
            except SettingsError as exc:
                return SettingsVerdict(refusal=str(exc))
    return SettingsVerdict()

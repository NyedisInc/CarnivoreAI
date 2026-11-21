
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

NETWORK_PREFIX = "network_hosts:"
NETWORK_WRITE_PREFIX = "network_hosts.write:"
LAN_PREFIX = "lan_hosts:"
LAN_WRITE_PREFIX = "lan_hosts.write:"
PERMISSION_PREFIXES = (NETWORK_PREFIX, NETWORK_WRITE_PREFIX, LAN_PREFIX, LAN_WRITE_PREFIX)
READ_METHODS = ("GET", "HEAD")
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
FORBIDDEN_HEADERS = frozenset({"host", "cookie", "content-length", "connection", "transfer-encoding", "te", "upgrade",
                               "accept-encoding", "expect"})
FORBIDDEN_HEADER_PREFIXES = ("proxy-", "x-forwarded-", "sec-")
_DNS_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_TOKEN = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_SECRET_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_ENTRY_FIELDS = frozenset({"host", "reason", "methods", "paths", "auth"})
_LAN_FIELDS = frozenset({"host", "reason", "methods", "paths"})
_SECRET_FIELDS = frozenset({"name", "label", "help"})


class NetworkDeclError(ValueError):
    pass


@dataclass(frozen=True)
class Auth:

    secret: str
    header: str
    scheme: str


@dataclass(frozen=True)
class NetworkHost:

    host: str
    reason: str
    methods: Tuple[str, ...]
    paths: Tuple[str, ...]
    auth: Optional[Auth]

    @property
    def permission(self) -> str:
        return NETWORK_PREFIX + self.host

    @property
    def write_permission(self) -> str:
        return NETWORK_WRITE_PREFIX + self.host


@dataclass(frozen=True)
class LanHost:

    scheme: str
    host: str
    port: int
    reason: str
    methods: Tuple[str, ...]
    paths: Tuple[str, ...]

    @property
    def entry(self) -> str:
        return f"{self.scheme}://{self.host_for_url}:{self.port}"

    @property
    def host_for_url(self) -> str:
        return f"[{self.host}]" if ":" in self.host else self.host

    @property
    def permission(self) -> str:
        return LAN_PREFIX + self.entry

    @property
    def write_permission(self) -> str:
        return LAN_WRITE_PREFIX + self.entry


@dataclass(frozen=True)
class Secret:

    name: str
    label: str
    help: str


@dataclass(frozen=True)
class NetworkDecl:

    network_hosts: Tuple[NetworkHost, ...] = ()
    lan_hosts: Tuple[LanHost, ...] = ()
    secrets: Tuple[Secret, ...] = ()

    def secret_hosts(self, name: str) -> Tuple[str, ...]:
        return tuple(sorted({h.host for h in self.network_hosts if h.auth and h.auth.secret == name}))


def literal_kind(host: str) -> Optional[str]:
    bare = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        return "canonical" if str(ipaddress.ip_address(bare)) == bare else "odd"
    except ValueError:
        pass
    try:
        socket.inet_aton(bare)
        return "odd"
    except OSError:
        return None


def normalize_host(host: str) -> str:
    name = host.strip().rstrip(".").lower()
    if not name or any(c in name for c in " /\\@?#%*"):
        raise ValueError("bad host")
    try:
        return name.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("bad host") from exc


def _methods(where: str, raw: Any) -> Tuple[str, ...]:
    if raw is None:
        return READ_METHODS
    allowed = READ_METHODS + WRITE_METHODS
    if not isinstance(raw, list) or not raw or any(m not in allowed for m in raw) or len(set(raw)) != len(raw):
        raise NetworkDeclError(f"{where}.methods must be a list of distinct names from {allowed}")
    return tuple(raw)


def _paths(where: str, raw: Any) -> Tuple[str, ...]:
    if raw is None:
        return ("/",)
    ok = isinstance(raw, list) and raw and all(
        isinstance(p, str) and p.startswith("/") and not re.search(r"[?#\\\s%]|(^|/)\.\.?(/|$)", p) for p in raw)
    if not ok:
        raise NetworkDeclError(f"{where}.paths must be a list of path prefixes starting with / (no query, fragment, dot segment or escape)")
    return tuple(raw)


def _reason(where: str, block: Mapping[str, Any]) -> str:
    reason = block.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise NetworkDeclError(f"{where}.reason is required")
    return reason.strip()


def _network_host(cplug_id: str, i: int, block: Any, secrets: Mapping[str, Secret]) -> NetworkHost:
    where = f"{cplug_id}: network_hosts[{i}]"
    if not isinstance(block, dict) or set(block) - _ENTRY_FIELDS or not isinstance(block.get("host"), str):
        raise NetworkDeclError(f"{where} must be an object of {sorted(_ENTRY_FIELDS)} with a host")
    try:
        host = normalize_host(block["host"])
    except ValueError as exc:
        raise NetworkDeclError(f"{where}.host is not a valid host name") from exc
    labels = host.split(".")
    if literal_kind(host) or len(labels) < 2 or not all(_DNS_LABEL.match(x) for x in labels) or host.endswith(".local"):
        raise NetworkDeclError(f"{where}.host must be an exact public DNS name (no IP literal, wildcard, single label or .local; use lan_hosts)")
    auth = None
    if block.get("auth") is not None:
        raw = block["auth"]
        if (not isinstance(raw, dict) or set(raw) != {"secret", "header", "scheme"} or raw["secret"] not in secrets
                or not isinstance(raw["header"], str) or not _TOKEN.match(raw["header"])
                or raw["header"].lower() in FORBIDDEN_HEADERS or raw["header"].lower().startswith(FORBIDDEN_HEADER_PREFIXES)
                or not isinstance(raw["scheme"], str) or not re.match(r"^[A-Za-z0-9-]{0,32}$", raw["scheme"])):
            raise NetworkDeclError(f"{where}.auth must name a declared secret, a plain header and a scheme")
        auth = Auth(raw["secret"], raw["header"], raw["scheme"])
    return NetworkHost(host, _reason(where, block), _methods(where, block.get("methods")), _paths(where, block.get("paths")), auth)


def _lan_host(cplug_id: str, i: int, block: Any) -> LanHost:
    from urllib.parse import urlsplit  # noqa: PLC0415

    where = f"{cplug_id}: lan_hosts[{i}]"
    if not isinstance(block, dict) or set(block) - _LAN_FIELDS or not isinstance(block.get("host"), str):
        raise NetworkDeclError(f"{where} must be an object of {sorted(_LAN_FIELDS)} with a host")
    try:
        parts = urlsplit(block["host"])
        port = parts.port
        name = normalize_host(parts.hostname or "")
    except ValueError as exc:
        raise NetworkDeclError(f"{where}.host must be scheme://address-or-name:port") from exc
    if parts.scheme not in ("http", "https") or port is None or parts.path not in ("", "/") or parts.query or parts.fragment or parts.username:
        raise NetworkDeclError(f"{where}.host must be scheme://address-or-name:port (http or https, a port, nothing else)")
    kind = literal_kind(name)
    if kind == "odd":
        raise NetworkDeclError(f"{where}.host must be a canonical address")
    if kind is None:
        if not name.endswith(".local") or not all(_DNS_LABEL.match(x) for x in name.split(".")):
            raise NetworkDeclError(f"{where}.host must be a private address or a .local name")
    else:
        ip = ipaddress.ip_address(name)
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_global:
            raise NetworkDeclError(f"{where}.host is never reachable or not a private address")
    return LanHost(parts.scheme, name, port, _reason(where, block), _methods(where, block.get("methods")),
                   _paths(where, block.get("paths")))


def _secret(cplug_id: str, i: int, block: Any) -> Secret:
    where = f"{cplug_id}: secrets[{i}]"
    if (not isinstance(block, dict) or set(block) != _SECRET_FIELDS or not _SECRET_NAME.match(str(block["name"]))
            or not all(isinstance(block[k], str) and block[k].strip() for k in ("label", "help"))):
        raise NetworkDeclError(f"{where} must hold exactly {sorted(_SECRET_FIELDS)}, the name matching {_SECRET_NAME.pattern}")
    return Secret(block["name"], block["label"].strip(), block["help"].strip())


def parse_network(cplug_id: str, raw: Mapping[str, Any], permissions: Tuple[str, ...]) -> NetworkDecl:
    for key in ("network_hosts", "lan_hosts", "secrets"):
        if not isinstance(raw.get(key, []), list):
            raise NetworkDeclError(f"{cplug_id}: {key} must be a list")
    secrets = [_secret(cplug_id, i, b) for i, b in enumerate(raw.get("secrets", []))]
    if len({s.name for s in secrets}) != len(secrets):
        raise NetworkDeclError(f"{cplug_id}: secrets names one secret twice")
    by_name: Dict[str, Secret] = {s.name: s for s in secrets}
    hosts = [_network_host(cplug_id, i, b, by_name) for i, b in enumerate(raw.get("network_hosts", []))]
    lans = [_lan_host(cplug_id, i, b) for i, b in enumerate(raw.get("lan_hosts", []))]
    if len({h.host for h in hosts}) != len(hosts) or len({h.entry for h in lans}) != len(lans):
        raise NetworkDeclError(f"{cplug_id}: network_hosts or lan_hosts names one host twice")
    wanted = set()
    for entry in (*hosts, *lans):
        wanted.add(entry.permission)
        if any(m in WRITE_METHODS for m in entry.methods):
            wanted.add(entry.write_permission)
    asked = {p for p in permissions if p.startswith(PERMISSION_PREFIXES)}
    if asked != wanted:
        raise NetworkDeclError(f"{cplug_id}: the network permissions {sorted(asked)} must match the declared entries {sorted(wanted)}")
    return NetworkDecl(tuple(hosts), tuple(lans), tuple(secrets))

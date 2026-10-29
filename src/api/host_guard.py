
from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
import sys
from typing import Any, Awaitable, Callable, FrozenSet, MutableMapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import structlog

from src.core.product_identity import env_names

logger = structlog.get_logger()

ASGIApp = Callable[[MutableMapping[str, Any], Callable, Callable], Awaitable[None]]

ALLOWED_HOSTS_KEY = env_names("ALLOWED_HOSTS")[0]

UNTRUSTED_CLOSE_CODE = 4406

_LOG_VALUE_MAX = 200

_LABEL = r"[a-z0-9]([a-z0-9-]*[a-z0-9])?"
_ALLOWED_ENTRY = re.compile(rf"^(\*\.)?{_LABEL}(\.{_LABEL})*$")


def split_host_port(value: str) -> Optional[Tuple[str, Optional[int]]]:
    value = value.strip()
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return None
        host, rest = value[1:end], value[end + 1:]
        if rest and not rest.startswith(":"):
            return None
        port_text: Optional[str] = rest[1:] if rest else None
    elif value.count(":") == 1:
        host, port_text = value.split(":")
    else:
        host, port_text = value, None
    host = host.lower()
    if host.endswith("."):
        host = host[:-1]
    if not host:
        return None
    if port_text is None:
        return host, None
    if not port_text.isdigit() or not 0 < int(port_text) < 65536:
        return None
    return host, int(port_text)


def is_ip_literal(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True


def machine_names() -> FrozenSet[str]:
    names = set()
    try:
        hostname = socket.gethostname().lower().rstrip(".")
    except OSError as exc:
        logger.warning("host_guard_hostname_unavailable", error=str(exc))
        hostname = ""
    bare = hostname[:-6] if hostname.endswith(".local") else hostname
    if bare:
        names.update((bare, f"{bare}.local"))
        first = bare.split(".", 1)[0]
        if first and first != bare:
            names.update((first, f"{first}.local"))
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["scutil", "--get", "LocalHostName"],
                capture_output=True, text=True, timeout=2, check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("host_guard_local_hostname_unavailable", error=str(exc))
        else:
            local = result.stdout.strip().lower()
            if local:
                names.add(f"{local}.local")
    return frozenset(names)


def parse_allowed_hosts(raw: Optional[str]) -> Tuple[FrozenSet[str], Tuple[str, ...], bool]:
    exact, suffixes, allow_any = set(), [], False
    for entry in (raw or "").split(","):
        entry = entry.strip().lower().rstrip(".")
        if not entry:
            continue
        if entry == "*":
            allow_any = True
        elif _ALLOWED_ENTRY.match(entry):
            if entry.startswith("*."):
                suffixes.append(entry[1:])
            else:
                exact.add(entry)
        else:
            logger.warning("allowed_hosts_entry_ignored", entry=entry[:_LOG_VALUE_MAX], key=ALLOWED_HOSTS_KEY)
    return frozenset(exact), tuple(suffixes), allow_any


class HostPolicy:

    def __init__(self, extra_hosts: Optional[str], allowed_origins: Sequence[str] = ()) -> None:
        self._origins = frozenset(o.strip().lower().rstrip("/") for o in allowed_origins)
        self._names = machine_names()
        self._exact, self._suffixes, self.allow_any = parse_allowed_hosts(extra_hosts)
        if self.allow_any:
            logger.warning("host_check_disabled", key=ALLOWED_HOSTS_KEY)

    def configured(self, hostname: str) -> bool:
        return hostname in self._exact or any(
            hostname.endswith(suffix) for suffix in self._suffixes
        )

    def host_trusted(self, host_header: Optional[str]) -> bool:
        if self.allow_any:
            return True
        parsed = split_host_port(host_header) if host_header else None
        if parsed is None:
            return False
        hostname = parsed[0]
        return (
            is_ip_literal(hostname)
            or hostname == "localhost"
            or hostname.endswith(".localhost")
            or hostname in self._names
            or self.configured(hostname)
        )


    def origin_trusted(self, origin: Optional[str], host_header: Optional[str]) -> bool:
        if origin is None:
            return True
        normalized = origin.strip().lower().rstrip("/")
        if normalized in self._origins:
            return True
        parts = urlsplit(normalized)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        try:
            origin_port = parts.port
        except ValueError:
            return False
        origin_host = parts.hostname.rstrip(".")
        if self.configured(origin_host):
            return True
        target = split_host_port(host_header) if host_header else None
        if target is None or target[0] != origin_host:
            return False
        origin_port = origin_port or (443 if parts.scheme == "https" else 80)
        return origin_port == target[1] if target[1] is not None else origin_port in (80, 443)


def _header(scope: MutableMapping[str, Any], name: bytes) -> Optional[str]:
    for key, value in scope.get("headers", ()):
        if key == name:
            return value.decode("latin-1")
    return None


def _is_link_host(scope: MutableMapping[str, Any], host_header: Optional[str]) -> bool:
    link_host = scope.get("link_host")
    if scope.get("via_link") is not True or not link_host or not host_header:
        return False
    parsed = split_host_port(host_header)
    return parsed is not None and parsed[0] == link_host and parsed[1] in (None, 443)


class HostGuardMiddleware:

    def __init__(
        self, app: ASGIApp, extra_hosts: Optional[str] = None, allowed_origins: Sequence[str] = ()
    ) -> None:
        self.app = app
        self.policy = HostPolicy(extra_hosts, allowed_origins)

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[MutableMapping[str, Any]]],
        send: Callable[[MutableMapping[str, Any]], Awaitable[None]],
    ) -> None:
        kind = scope["type"]
        if kind not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        host = _header(scope, b"host")
        client = scope.get("client")
        where = {"path": scope.get("path", ""), "client_ip": client[0] if client else None}
        if not (self.policy.host_trusted(host) or _is_link_host(scope, host)):
            logger.warning("host_rejected", host=(host or "")[:_LOG_VALUE_MAX], scope_type=kind, **where)
            await refuse(kind, send, f"untrusted host header. to reach this server by that name, add it to {ALLOWED_HOSTS_KEY}.\n")
            return
        origin = _header(scope, b"origin") if kind == "websocket" else None
        if not self.policy.origin_trusted(origin, host):
            logger.warning(
                "websocket_origin_rejected",
                origin=(origin or "")[:_LOG_VALUE_MAX],
                host=(host or "")[:_LOG_VALUE_MAX],
                **where,
            )
            await refuse(kind, send, "")
            return
        await self.app(scope, receive, send)


async def refuse(
    kind: str, send: Callable[[MutableMapping[str, Any]], Awaitable[None]], body: str
) -> None:
    if kind == "websocket":
        await send({"type": "websocket.close", "code": UNTRUSTED_CLOSE_CODE, "reason": ""})
        return
    payload = body.encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": 400,
        "headers": [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"content-length", str(len(payload)).encode("ascii")),
            (b"x-content-type-options", b"nosniff"),
        ],
    })
    await send({"type": "http.response.body", "body": payload})

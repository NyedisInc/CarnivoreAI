
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional
from urllib.parse import quote

import structlog

from src.api import host_guard
from src.config import settings
from src.core import setup_state, workspace_settings
from src.core.tmux_backend import _slugify

logger = structlog.get_logger()

CACHE_SECONDS = 60.0

KIND_MOBILE = "mobile_sync"
KIND_LOCAL_NAME = "local_name"
KIND_LAN_IP = "lan_ip"
KIND_NONE = "none"

REASON_MOBILE_READY = "mobile_sync_ready"
REASON_MOBILE_NOT_SET_UP = "mobile_sync_not_set_up"
REASON_LOCAL_NAME_READY = "local_name_ready"
REASON_LAN_IP_READY = "lan_ip_ready"
REASON_LOOPBACK_ONLY = "bound_loopback_only"
REASON_BIND_UNKNOWN = "bound_host_unknown"
REASON_NO_LAN_ADDRESS = "no_lan_address"


@dataclass(frozen=True)
class LinkResult:

    kind: str
    base: str
    reason: str


def session_path(session_slug: str) -> str:
    return f"/session/{quote(_slugify(session_slug), safe='')}"


def deep_link(base: str, session_slug: str) -> Optional[str]:
    if not base:
        return None
    return f"{base.rstrip('/')}{session_path(session_slug)}"


def _is_loopback(host: Optional[str]) -> bool:
    value = (host or "").strip().lower()
    return value in ("", "localhost", "::1") or value.startswith("127.")


def _mobile_base(manager: Any) -> Optional[str]:
    if manager is None or not manager.available:
        return None
    if not manager.pairing.enabled or manager.pairing.device_count() < 1:
        return None
    host = manager.public_host()
    return f"https://{host}" if host else None


class LinkResolver:

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        bound_host: Callable[[], Optional[str]] = setup_state.recorded_bound_host,
        machine_names: Callable[[], Any] = host_guard.machine_names,
        ipv4_addresses: Callable[[], List[str]] = workspace_settings.machine_ipv4_addresses,
        port: Callable[[], int] = lambda: settings.port,
    ) -> None:
        self._clock = clock
        self._bound_host = bound_host
        self._machine_names = machine_names
        self._ipv4 = ipv4_addresses
        self._port = port
        self._cached: Optional[LinkResult] = None
        self._expires = 0.0

    def resolve_blocking(self, manager: Any) -> LinkResult:
        now = self._clock()
        if self._cached is not None and now < self._expires:
            return self._cached
        result = self._compute(manager)
        self._cached, self._expires = result, now + CACHE_SECONDS
        return result

    async def resolve(self, manager: Any) -> LinkResult:
        return await asyncio.to_thread(self.resolve_blocking, manager)

    def _compute(self, manager: Any) -> LinkResult:
        mobile = _mobile_base(manager)
        if mobile:
            return LinkResult(KIND_MOBILE, mobile, REASON_MOBILE_READY)
        bound = self._bound_host()
        if _is_loopback(bound):
            reason = REASON_BIND_UNKNOWN if not (bound or "").strip() else REASON_LOOPBACK_ONLY
            return LinkResult(KIND_NONE, "", reason)
        port = self._port()
        local_names = sorted(n for n in self._machine_names() if n.endswith(".local"))
        if local_names:
            return LinkResult(KIND_LOCAL_NAME, f"http://{local_names[0]}:{port}", REASON_MOBILE_NOT_SET_UP)
        addresses = [a for a in self._ipv4() if not a.startswith("127.")]
        if addresses:
            return LinkResult(KIND_LAN_IP, f"http://{addresses[0]}:{port}", REASON_MOBILE_NOT_SET_UP)
        return LinkResult(KIND_NONE, "", REASON_NO_LAN_ADDRESS)


resolver = LinkResolver()

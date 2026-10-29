
from __future__ import annotations

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def ws_deflate_for(bind_host: str) -> bool:
    return (bind_host or "").strip().lower() not in _LOOPBACK_HOSTS

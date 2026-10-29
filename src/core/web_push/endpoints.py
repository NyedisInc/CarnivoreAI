
from __future__ import annotations

import re
from urllib.parse import urlsplit

import httpx

EXACT_HOSTS = frozenset({"web.push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com"})
SUFFIXES = (".push.apple.com",)
MAX_ENDPOINT_LENGTH = 2048
_LABELS = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*$")
_UNSAFE = re.compile(r"[\x00-\x20\x7f\\]")


def endpoint_allowed(endpoint: object) -> bool:
    if not isinstance(endpoint, str) or not endpoint.isascii() or len(endpoint) > MAX_ENDPOINT_LENGTH:
        return False
    if _UNSAFE.search(endpoint):
        return False
    try:
        parts = urlsplit(endpoint)
        port = parts.port
        host = (parts.hostname or "").lower()
        if httpx.URL(endpoint).host != host:
            return False
    except (ValueError, httpx.InvalidURL):
        return False
    if parts.scheme != "https" or parts.username or parts.password or port is not None:
        return False
    if not _LABELS.match(host):
        return False
    return host in EXACT_HOSTS or host.endswith(SUFFIXES)


def host_of(endpoint: str) -> str:
    try:
        return (urlsplit(endpoint).hostname or "").lower()
    except ValueError:
        return ""

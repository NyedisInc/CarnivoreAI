
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

import httpx
import structlog

logger = structlog.get_logger()

RESOLVERS = ("https://cloudflare-dns.com/dns-query", "https://dns.google/resolve")
TIMEOUT = 5.0
_TYPE_CAA = 257
_PIN = re.compile(r'accounturi=([^\s";]+)')
Fetch = Callable[[str, str], Awaitable[Any]]


async def _fetch(url: str, name: str) -> Any:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        reply = await client.get(url, params={"name": name, "type": "CAA"}, headers={"Accept": "application/dns-json"})
        reply.raise_for_status()
        return reply.json()


def _text(data: str) -> str:
    if data.startswith("\\#"):
        try:
            return bytes.fromhex("".join(data.split()[2:])).decode("ascii", "replace")
        except ValueError:
            return ""
    return data


async def pin_visible(node: str, acct_uri: str, *, fetch: Fetch = _fetch) -> bool:
    async def one(url: str) -> bool:
        try:
            reply = await fetch(url, node)
            return reply.get("Status") == 0 and any(
                isinstance(a, dict) and a.get("type") == _TYPE_CAA
                and acct_uri in _PIN.findall(_text(str(a.get("data", ""))))
                for a in (reply.get("Answer") or []))
        except (httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
            logger.info("custom_domain_doh_failed", resolver=url, error_type=type(exc).__name__)
            return False

    return all([await one(url) for url in RESOLVERS])


from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import structlog

from src.core.computers.direction import REFUSAL_CODE
from src.core.federation import peer_links
from src.core.federation.peer_fanout import _error_code
from src.core.federation.pairing import SCREENS_MINOR
from src.core.federation.peer_client import PeerRefused, PeerUnreachable

logger = structlog.get_logger()

PEER_TIMEOUT_SECONDS = 3.0
PEER_TOTAL_SECONDS = 4.0
PEER_MAX_BODY = 2 * 1024 * 1024
_STATUSES = {"ok", "gone", "unsupported"}
_MAX_GRID = 2000


@dataclass(frozen=True)
class PeerAsk:

    remote_id: str
    peer_id: str
    hash: Optional[str]


@dataclass(frozen=True)
class PeerGroup:

    install_id: str
    key: str
    asks: List[PeerAsk]


def _answer(status: str, data: Optional[dict] = None) -> dict:
    return {"status": status, **(data or {})}


def _clean(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict) or raw.get("status") not in _STATUSES:
        return None
    if raw["status"] != "ok":
        return {"status": raw["status"]}
    cols, rows, digest, screen = raw.get("cols"), raw.get("rows"), raw.get("hash"), raw.get("screen")
    ints_ok = all(isinstance(n, int) and not isinstance(n, bool) and 0 < n <= _MAX_GRID for n in (cols, rows))
    if not ints_ok or not isinstance(screen, str) or not isinstance(digest, str) or len(digest) > 64:
        return None
    return {"status": "ok", "cols": cols, "rows": rows, "hash": digest, "screen": screen}


async def _ask_one(group: PeerGroup) -> Dict[str, dict]:
    every = lambda status: {a.remote_id: _answer(status) for a in group.asks}  # noqa: E731
    links = peer_links.LINKS
    if links is None:
        return every("unreachable")
    client = links.client(group.install_id)
    if client is None:
        return every("unreachable")
    if links.minor(group.install_id) < SCREENS_MINOR:
        return every("older")
    items = [{"id": a.peer_id, "hash": a.hash} for a in group.asks]
    try:
        reply = await client.request("POST", "/warroom/screens", json={"items": items},
                                     timeout=PEER_TIMEOUT_SECONDS, max_body=PEER_MAX_BODY)
    except PeerRefused:
        return every("unsupported")
    except (PeerUnreachable, OSError, asyncio.TimeoutError):
        return every("unreachable")
    if reply.status_code == 404:
        return every("older")
    if reply.status_code == 403 and _error_code(reply) == REFUSAL_CODE:
        return every("unsupported")
    if reply.status_code != 200:
        logger.info("warroom_peer_screens_refused", peer=group.key, status=reply.status_code)
        return every("unreachable")
    try:
        screens = reply.json().get("screens")
    except (ValueError, TypeError, AttributeError, RecursionError):
        screens = None
    if not isinstance(screens, dict):
        return every("unreachable")
    out: Dict[str, dict] = {}
    for ask in group.asks:
        if ask.peer_id not in screens:
            continue
        cleaned = _clean(screens[ask.peer_id])
        out[ask.remote_id] = cleaned if cleaned is not None else _answer("unreachable")
    return out


async def ask_peers(groups: List[PeerGroup]) -> Dict[str, dict]:
    results = await asyncio.gather(*(_ask_one(g) for g in groups), return_exceptions=True)
    merged: Dict[str, dict] = {}
    for group, part in zip(groups, results):
        if isinstance(part, BaseException):
            if isinstance(part, asyncio.CancelledError):
                raise part
            logger.warning("warroom_peer_screens_failed", peer=group.key, error_type=type(part).__name__)
            part = {a.remote_id: _answer("unreachable") for a in group.asks}
        merged.update(part)
    return merged

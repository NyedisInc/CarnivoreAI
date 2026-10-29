
from __future__ import annotations

from typing import Any, Callable, Dict, Optional
import sqlite3

import structlog

from src.core.federation import peer_hosts, peer_listing, shadow_rows
from src.core.listing_push.diff import KeyedRows, apply_change

logger = structlog.get_logger()


class _Held:

    def __init__(self, stream: str, seq: int, rows: KeyedRows, asleep: KeyedRows) -> None:
        self.stream, self.seq, self.rows, self.asleep = stream, seq, rows, asleep


_HELD: Dict[str, _Held] = {}


def drop(peer_install_id: str) -> None:
    _HELD.pop(peer_install_id, None)
    peer_listing.PUSHED.discard(peer_install_id)


def _next(frame: Dict[str, Any], held: Optional[_Held]) -> Optional[_Held]:
    stream, seq = frame.get("stream"), frame.get("seq")
    if not isinstance(stream, str) or not isinstance(seq, int) or isinstance(seq, bool):
        return None
    try:
        if frame.get("full") is True:
            rows, asleep = apply_change(None, frame.get("list")), apply_change(None, frame.get("asleep"))
        elif held is not None and held.stream == stream and seq == held.seq + 1:
            rows, asleep = apply_change(held.rows, frame.get("list")), apply_change(held.asleep, frame.get("asleep"))
        else:
            return None
    except (KeyError, TypeError, AttributeError, ValueError):
        return None
    if len(rows) > shadow_rows.MAX_ROWS or len(asleep) > shadow_rows.MAX_ROWS:
        return None
    return _Held(stream, seq, rows, asleep)


async def apply(frame: Dict[str, Any], peer: "peer_hosts.PeerRow", open_db: Callable[[], sqlite3.Connection]) -> bool:
    key = peer.peer_install_id
    if frame.get("resync") is True:
        drop(key)
        return True
    held = _next(frame, _HELD.get(key))
    if held is None:
        logger.info("peer_listing_push_unusable", peer=peer.key)
        return False
    if not await peer_listing.ingest(peer, open_db, [row for _, row in held.rows], [row for _, row in held.asleep]):
        return False
    _HELD[key] = held
    peer_listing.PUSHED.add(key)
    return True

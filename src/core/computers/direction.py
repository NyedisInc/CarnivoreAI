
from __future__ import annotations

import sqlite3
import threading
from typing import Any, Set

from src.core.computers import store

ONE_WAY_ALLOWED = frozenset({
    "/api/v1/federation/hello", "/api/v1/federation/link", "/api/v1/federation/grants/self",
    "/api/v1/federation/key/announce", "/api/v1/federation/link-cert", "/api/v1/federation/pack/exchange",
})

RESTRICTION_ONE_WAY = "one_way"

REFUSAL_CODE = "computer_one_way"


def inbound_allowed(conn: sqlite3.Connection, peer_install_id: str) -> bool:
    try:
        row = store.get(conn, peer_install_id)
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return True
        raise
    return row is None or row.inbound_control != 0


def path_allowed(path: str) -> bool:
    return path in ONE_WAY_ALLOWED


def contained(peer_install_id: str) -> bool:
    row = store.CACHE.get(peer_install_id)
    return row is not None and row.inbound_control == 0


_ONE_WAY_TOWARD: Set[str] = set()
_TOWARD_LOCK = threading.Lock()


def note_restrictions(peer_install_id: str, restrictions: Any) -> None:
    one_way = isinstance(restrictions, list) and RESTRICTION_ONE_WAY in restrictions
    with _TOWARD_LOCK:
        (_ONE_WAY_TOWARD.add if one_way else _ONE_WAY_TOWARD.discard)(peer_install_id)


def is_one_way_toward(peer_install_id: str) -> bool:
    with _TOWARD_LOCK:
        return peer_install_id in _ONE_WAY_TOWARD

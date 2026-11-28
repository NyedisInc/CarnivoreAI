
from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

from src.plugins.taskmanager import lane
from src.plugins.taskmanager.cards import projection

MOVES: List[Tuple[int, str, str, str]] = []
_lock = threading.Lock()
_local = threading.local()
_MIRRORED = ("in_progress", "done")
_PROJECTED = ("state", "card_parent", "card_accepted_at", "card_holder", "claude_working", "card_queued")


def _col(prefix: str) -> str:
    return re.sub(r"\b(" + "|".join(_PROJECTED) + r")\b", prefix + r".\1", projection.COLUMN_SQL)


_TRIGGER = (f"CREATE TEMP TRIGGER IF NOT EXISTS card_column_moved AFTER UPDATE OF {', '.join(_PROJECTED)} ON main.work_items "
            f"WHEN new.card_origin LIKE '{lane.ARGENT_ORIGIN}:%' AND {_col('old')} != {_col('new')} "
            f"BEGIN SELECT card_column_moved(new.id, {_col('old')}, {_col('new')}); END")


def install(conn: sqlite3.Connection) -> None:
    conn.create_function("card_column_moved", 3, _moved)
    conn.execute(_TRIGGER)


def _moved(card_id: int, before: str, after: str) -> int:
    hinted: Optional[Tuple[Optional[int], bool, str]] = getattr(_local, "hint", None)
    if hinted is not None and hinted[1]:
        return 0
    reason = hinted[2] if hinted is not None and hinted[0] == card_id else ""
    with _lock:
        MOVES.append((int(card_id), before, after, reason))
    return 0


@contextmanager
def hint(card_id: Optional[int], args: Mapping[str, Any], op: str) -> Iterator[None]:
    _local.hint = (card_id, bool(args.get("from_tracker")), str(args.get("reason") or "") if op == "done" else "")
    try:
        yield
    finally:
        _local.hint = None


def drain() -> List[Tuple[int, str, str, str]]:
    with _lock:
        taken = list(MOVES)
        MOVES.clear()
    net: Dict[int, Tuple[str, str, str]] = {}
    for card_id, before, after, reason in taken:
        first, _, last_reason = net.get(card_id, (before, after, ""))
        net[card_id] = (first, after, reason or last_reason)
    return [(card_id, before, after, reason) for card_id, (before, after, reason) in net.items() if before != after and after in _MIRRORED]

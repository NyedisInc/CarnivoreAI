
from __future__ import annotations

import json
import time
from typing import Any, Dict, FrozenSet, Optional, Set, Tuple

from src.core.computers import direction
from src.core.notifications import doc_model
from src.core.notifications.sync import sanitize

KIND = "notify"
CAP, ORIGIN_CAP, RESERVE = sanitize.MAX_ENTRIES, 2000, 500
TOMB_TTL_MS = doc_model.TOMBSTONE_TTL_SECONDS * 1000
MAX_COUNTER = 2 ** 53 - 1
MAX_VALUE_BYTES = 4096
ALLOWED: Tuple[str, ...] = (doc_model.KIND_TICK, doc_model.KIND_EXTRA, doc_model.KIND_DEFAULT, doc_model.KIND_MUTE, doc_model.KIND_STYLE,
                            doc_model.KIND_ROUTE, doc_model.KIND_ON)

START: Tuple[bool, FrozenSet[str]] = (True, frozenset())
_GATES: Dict[str, Tuple[bool, FrozenSet[str]]] = {}
_FRESH: Set[str] = set()


def set_gate(own: str, out: bool, off: Any) -> None:
    _GATES[own] = (bool(out), frozenset(off))
    _FRESH.add(own)


def mark_failed(own: str) -> None:
    _FRESH.discard(own)


def gate(own: str) -> Tuple[bool, FrozenSet[str]]:
    return _GATES.get(own, START)


def local_ok(own: str, peer: Optional[str]) -> bool:
    out, off = gate(own)
    return own in _FRESH and not out and (peer is None or peer == own or peer not in off)


def forget_ok(own: str) -> bool:
    return own in _FRESH and gate(own)[0]


def _text(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def valid_shape(v: Any) -> bool:
    return isinstance(v, dict) and "ver" in v and set(v) <= {"val", "tomb", "ver"}


def valid(key: str, v: Any) -> bool:
    if not isinstance(key, str) or not valid_shape(v):
        return False
    try:
        if doc_model.parse_path(key).kind not in ALLOWED:
            return False
        if doc_model.parse_version(v["ver"])[0] > MAX_COUNTER:
            return False
        cleaned = sanitize.clean_entry(key, v, time.time())
        return cleaned is not None and _text(cleaned) == _text(v) and len(_text(v)) <= MAX_VALUE_BYTES
    except (ValueError, TypeError, RecursionError):
        return False


def is_tomb(v: Any) -> bool:
    return isinstance(v, dict) and "tomb" in v


def origin_ok(lst: Any, origin: Optional[str]) -> bool:
    entry = lst.entry(origin) if origin is not None and hasattr(lst, "entry") else None
    return entry is not None and not entry.one_way


def privileged(lst: Any, origin: Optional[str]) -> bool:
    return origin is not None and origin in (lst.alpha, lst.home)


def serve_ok(lst: Any, peer: Optional[str]) -> bool:
    return origin_ok(lst, peer) and not direction.contained(peer)

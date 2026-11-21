
from __future__ import annotations

import os
import re
import threading
import time
from typing import Any, Callable, Dict, Optional, Set, Tuple

from src.core.attention import fs_event_index

MAX_AGE_SECONDS: float = fs_event_index.RESCAN_SECONDS

PRUNE_ABOVE = 256

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)

_ENTRIES: Dict[Tuple[str, str], Tuple[float, Any]] = {}
_GENERATIONS: Dict[str, int] = {}
_resyncs = 0
_LOCK = threading.Lock()
_subscribed_to: Optional[fs_event_index.FsEventIndex] = None
_real_roots: Dict[Tuple[str, ...], Tuple[str, ...]] = {}
_real_paths: Dict[str, str] = {}


def conversation_uuid(path: str) -> Optional[str]:
    parts = path.split(os.sep)
    if "subagents" in parts:
        owner = parts[parts.index("subagents") - 1] if parts.index("subagents") > 0 else ""
        return owner.lower() if _UUID_RE.fullmatch(owner) else None
    name = parts[-1]
    stem = name[:-len(".jsonl")] if name.endswith(".jsonl") else name
    if _UUID_RE.fullmatch(stem):
        return stem.lower()
    return parts[-2].lower() if len(parts) > 1 and _UUID_RE.fullmatch(parts[-2]) else None


def changed(paths: Set[str]) -> None:
    global _resyncs
    with _LOCK:
        if fs_event_index.RESYNC in paths:
            _ENTRIES.clear()
            _resyncs += 1
            return
        hit = {uuid for uuid in (conversation_uuid(p) for p in paths) if uuid}
        for uuid in hit:
            _GENERATIONS[uuid] = _GENERATIONS.get(uuid, 0) + 1
        for key in [key for key in _ENTRIES if key[1] in hit]:
            del _ENTRIES[key]


def _generation(uuid: str) -> Tuple[int, int]:
    return _resyncs, _GENERATIONS.get(uuid, 0)


def _real(path: str) -> str:
    found = _real_paths.get(path)
    if found is None:
        found = _real_paths[path] = os.path.realpath(path)
    return found


def _live_index(parent: str) -> bool:
    global _subscribed_to
    index = fs_event_index.current()
    if index is None or not index.watching:
        return False
    watched = index._watched  # noqa: SLF001
    roots = _real_roots.get(watched)
    if roots is None:
        roots = _real_roots[watched] = tuple(_real(root) for root in watched)
    target = _real(parent)
    if not any(target == root or target.startswith(root + os.sep) for root in roots):
        return False
    with _LOCK:
        if _subscribed_to is not index:
            _ENTRIES.clear()
            index.subscribe(changed)
            _subscribed_to = index
    return True


def _copy(answer: Any) -> Any:
    return list(answer) if isinstance(answer, list) else answer


def remembered(parent: str, compute: Callable[[], Tuple[Any, bool]]) -> Any:
    uuid = conversation_uuid(parent)
    if uuid is None or not _live_index(parent):
        return compute()[0]
    key = (parent, uuid)
    now = time.monotonic()
    with _LOCK:
        entry = _ENTRIES.get(key)
        before = _generation(uuid)
    if entry is not None and now - entry[0] < MAX_AGE_SECONDS:
        return _copy(entry[1])
    answer, complete = compute()
    if complete and answer is not None:
        with _LOCK:
            if _generation(uuid) == before:
                if len(_ENTRIES) > PRUNE_ABOVE:
                    for old in [k for k, (at, _a) in _ENTRIES.items() if now - at >= MAX_AGE_SECONDS]:
                        del _ENTRIES[old]
                _ENTRIES[key] = (now, _copy(answer))
    return answer


def forget_all() -> None:
    with _LOCK:
        _ENTRIES.clear()


__all__ = ["MAX_AGE_SECONDS", "PRUNE_ABOVE", "changed", "conversation_uuid", "forget_all", "remembered"]

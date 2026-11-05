
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, NamedTuple, Optional, Sequence, Tuple

import structlog

from src.core.session_transcript_presence import is_racy, root_children

logger = structlog.get_logger()

STAMP_REUSE_SECONDS = 2.0

MAX_ABSENT_ENTRIES = 1024


@dataclass(frozen=True)
class CorpusStamp:

    root: str
    root_stamp: Tuple[int, int]
    children: Tuple[Tuple[int, int], ...]


class _StampMemo(NamedTuple):

    at: float
    stamp: Optional[CorpusStamp]
    root_mtime_ns: int


_lock = threading.Lock()
_stamps: Dict[str, _StampMemo] = {}
_absent: Dict[str, Tuple[Tuple[CorpusStamp, ...], Optional[str]]] = {}


def _clock() -> float:
    return time.monotonic()


def _times(path: Path) -> Tuple[int, int]:
    info = os.stat(path)
    return info.st_mtime_ns, info.st_ctime_ns


def _measure_stamp(root: Path, root_stamp: Tuple[int, int]) -> Optional[CorpusStamp]:
    if is_racy(root_stamp[0]):
        return None
    try:
        children, _from_cache = root_children(root)
        times = []
        for child in children:
            pair = _times(child)
            if is_racy(pair[0]):
                return None
            times.append(pair)
    except OSError as exc:
        logger.debug("transcript_absence_stamp_unreadable", root=str(root), error=str(exc))
        return None
    return CorpusStamp(str(root), root_stamp, tuple(times))


def corpus_stamp(root: Path) -> Optional[CorpusStamp]:
    try:
        root_stamp = _times(root)
    except OSError:
        return None
    key = str(root)
    now = _clock()
    with _lock:
        hit = _stamps.get(key)
    if hit is not None and now - hit.at < STAMP_REUSE_SECONDS and hit.root_mtime_ns == root_stamp[0]:
        return hit.stamp
    stamp = _measure_stamp(root, root_stamp)
    with _lock:
        _stamps[key] = _StampMemo(now, stamp, root_stamp[0])
    return stamp


def stamps_for(roots: Sequence[Path]) -> Optional[Tuple[CorpusStamp, ...]]:
    out = []
    for root in roots:
        stamp = corpus_stamp(root)
        if stamp is None:
            return None
        out.append(stamp)
    return tuple(out)


def known_absent(uuid: str, stamps: Tuple[CorpusStamp, ...]) -> Optional[str]:
    with _lock:
        hit = _absent.get(uuid)
    if hit is not None and hit[0] == stamps:
        return hit[1] or ""
    return None


def remember_absent(uuid: str, stamps: Tuple[CorpusStamp, ...], detail: Optional[str]) -> None:
    with _lock:
        if len(_absent) >= MAX_ABSENT_ENTRIES and uuid not in _absent:
            _absent.clear()
        _absent[uuid] = (stamps, detail)


def forget_all() -> None:
    with _lock:
        _stamps.clear()
        _absent.clear()

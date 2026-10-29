
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Iterable, Optional, Sequence, Tuple

import structlog

from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

TOPIC = "told"
KEEP = 1000


@dataclass(frozen=True)
class Told:

    list_key: str
    items: Optional[Tuple[int, ...]]
    told_at: int
    target_key: str
    label: str
    via: str
    at: float


_log: Deque[Told] = deque(maxlen=KEEP)


def note(ctx: CplugContext, keys: Iterable[str], told_at: int, target_key: str, label: str,
         items: Optional[Sequence[int]] = None, via: str = "") -> None:
    now = time.time()
    named = tuple(items) if items else None
    for key in keys:
        _log.append(Told(key, named, int(told_at), target_key, label or "", via or "", now))
    try:
        ctx.notify(TOPIC)
    except (AttributeError, RuntimeError, ValueError) as exc:
        logger.warning("task_manager_sent_notify_failed", error=str(exc))


def find(list_key: str, seq: int, item_id: Optional[int] = None) -> Optional[Told]:
    for entry in _log:
        if entry.list_key == list_key and entry.told_at >= seq and (entry.items is None or item_id is None or item_id in entry.items):
            return entry
    return None


def near(list_key: str, at: float, window_s: float) -> Optional[Told]:
    close = [e for e in _log if e.list_key == list_key and abs(e.at - at) <= window_s]
    return min(close, key=lambda e: abs(e.at - at)) if close else None


def reset() -> None:
    _log.clear()

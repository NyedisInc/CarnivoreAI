
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any, Dict, Hashable, Iterable, Mapping, Optional, Tuple

MAX_REUSE_SECONDS: float = 30.0


@dataclass(frozen=True)
class _Kept:

    key: Tuple[Any, ...]
    text: str
    started_wall: float
    started_mono: float


def screen_key(row: Mapping[str, Any]) -> Optional[Tuple[Any, ...]]:
    if row.get("pane_is_current") is not True or str(row.get("pane_dead")) != "0":
        return None
    parts = (row.get("pane_id"), row.get("pid"), row.get("created_at_epoch"),
             row.get("pane_width"), row.get("pane_height"))
    if any(part is None for part in parts) or not isinstance(row.get("window_activity"), int):
        return None
    return parts


class ScreenReuse:

    def __init__(self, *, max_reuse_seconds: float = MAX_REUSE_SECONDS) -> None:
        self._max_reuse = max_reuse_seconds
        self._lock = threading.Lock()
        self._kept: Dict[Hashable, _Kept] = {}

    def reusable(self, pane: Hashable, row: Mapping[str, Any],
                 now_wall: float, now_mono: float) -> Optional[str]:
        key = screen_key(row)
        if key is None:
            return None
        with self._lock:
            kept = self._kept.get(pane)
        if kept is None or kept.key != key:
            return None
        if now_wall < kept.started_wall or now_mono - kept.started_mono >= self._max_reuse:
            return None
        if row["window_activity"] >= math.floor(kept.started_wall):
            return None
        return kept.text

    def keep(self, pane: Hashable, row: Mapping[str, Any], text: Optional[str],
             started_wall: float, started_mono: float) -> None:
        key = screen_key(row)
        with self._lock:
            if text is None or key is None:
                self._kept.pop(pane, None)
            else:
                self._kept[pane] = _Kept(key, text, started_wall, started_mono)

    def retain_only(self, panes: Iterable[Hashable]) -> None:
        live = set(panes)
        with self._lock:
            for pane in [p for p in self._kept if p not in live]:
                del self._kept[pane]

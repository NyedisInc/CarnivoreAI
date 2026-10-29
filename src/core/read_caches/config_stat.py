
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Dict, Hashable, Tuple, TypeVar

T = TypeVar("T")

ENTRY_LIMIT = 64

StatKey = Tuple[int, int, int, int]


class ConfigReadCache:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: Dict[Tuple[Path, Hashable], Tuple[StatKey, object]] = {}

    def fetch(self, path: Path, key: Hashable, derive: Callable[[], T]) -> T:
        stat_key = _stat_key(path)
        if stat_key is None:
            return derive()
        slot = (path, key)
        with self._lock:
            hit = self._entries.get(slot)
        if hit is not None and hit[0] == stat_key:
            return hit[1]  # type: ignore[return-value]
        value = derive()
        with self._lock:
            self._entries[slot] = (stat_key, value)
            while len(self._entries) > ENTRY_LIMIT:
                self._entries.pop(next(iter(self._entries)))
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def _stat_key(path: Path) -> StatKey | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino


CONFIG_READS = ConfigReadCache()

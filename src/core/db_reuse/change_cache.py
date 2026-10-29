
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Hashable, Optional, Tuple

import structlog

logger = structlog.get_logger()


class ChangeCache:

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: Dict[Path, threading.RLock] = {}
        self._watchers: Dict[Path, Tuple[Tuple[int, int], sqlite3.Connection]] = {}
        self._entries: Dict[Path, Dict[Hashable, Tuple[int, Any]]] = {}
        self._opened: Dict[Hashable, Path] = {}

    def fetch(self, db_path: Path, key: Hashable, load: Callable[[], Any]) -> Any:
        with self._guard:
            lock = self._locks.setdefault(db_path, threading.RLock())
        with lock:
            version = self._version(db_path)
            if version is None:
                return load()
            hit = self._entries.get(db_path, {}).get(key)
            if hit is not None and hit[0] == version:
                return hit[1]
            value = load()
            self._entries.setdefault(db_path, {})[key] = (version, value)
            return value

    def fetch_opened(self, opener: Hashable, key: Hashable, load: Callable[[], Tuple[Any, Optional[Path]]]) -> Any:
        with self._guard:
            path = self._opened.get(opener)
        if path is None:
            value, real = load()
            self._learn(opener, real)
            return value
        with self._guard:
            lock = self._locks.setdefault(path, threading.RLock())
        with lock:
            version = self._version(path)
            hit = self._entries.get(path, {}).get((opener, key))
            if version is not None and hit is not None and hit[0] == version:
                return hit[1]
            value, real = load()
            if version is not None and real == path:
                self._entries.setdefault(path, {})[(opener, key)] = (version, value)
            else:
                self._learn(opener, real)
            return value

    def _learn(self, opener: Hashable, real: Optional[Path]) -> None:
        with self._guard:
            if real is None:
                self._opened.pop(opener, None)
            else:
                self._opened[opener] = real

    def _version(self, db_path: Path) -> int | None:
        try:
            stat = db_path.stat()
        except OSError:
            self._drop(db_path)
            return None
        identity = (stat.st_dev, stat.st_ino)
        held = self._watchers.get(db_path)
        try:
            if held is None or held[0] != identity:
                self._drop(db_path)
                held = (identity, sqlite3.connect(str(db_path), timeout=5.0, check_same_thread=False))
                self._watchers[db_path] = held
            return int(held[1].execute("PRAGMA data_version").fetchone()[0])
        except sqlite3.Error as exc:
            logger.warning("change_cache_unwatched", path=str(db_path), error=str(exc))
            self._drop(db_path)
            return None

    def _drop(self, db_path: Path) -> None:
        self._entries.pop(db_path, None)
        held = self._watchers.pop(db_path, None)
        if held is not None:
            held[1].close()

    def clear(self) -> None:
        with self._guard:
            entries, watchers = self._entries, self._watchers
            self._entries, self._watchers, self._opened = {}, {}, {}
        entries.clear()
        for _identity, conn in watchers.values():
            conn.close()


def main_file(conn: sqlite3.Connection) -> Optional[Path]:
    for row in conn.execute("PRAGMA database_list").fetchall():
        if row[1] == "main":
            return Path(row[2]) if row[2] else None
    return None


CACHE = ChangeCache()


HOT_READS = ChangeCache()


from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()


_ORPHANS: Dict[int, List[sqlite3.Connection]] = {}
_ORPHAN_LOCK = threading.Lock()
_REAPERS = threading.local()


def _close_quietly(conn: sqlite3.Connection) -> None:
    try:
        conn.close()
    except sqlite3.Error as exc:
        logger.debug("pooled_connection_close_failed", error=str(exc))


def _close_orphans(ident: int) -> None:
    if not _ORPHANS:
        return
    with _ORPHAN_LOCK:
        mine = _ORPHANS.pop(ident, [])
    for conn in mine:
        _close_quietly(conn)


class _Reaper:

    def __init__(self) -> None:
        self.ident = threading.get_ident()

    def __del__(self) -> None:
        if threading.get_ident() == self.ident:
            _close_orphans(self.ident)


class _Holder:

    def __init__(self) -> None:
        self.slots: Dict[str, Tuple[sqlite3.Connection, int]] = {}
        self.owner = threading.get_ident()
        if getattr(_REAPERS, "reaper", None) is None:
            _REAPERS.reaper = _Reaper()
        _close_orphans(self.owner)

    def close_all(self) -> None:
        slots, self.slots = self.slots, {}
        conns = [conn for conn, _inode in slots.values()]
        if threading.get_ident() != self.owner:
            if conns:
                with _ORPHAN_LOCK:
                    _ORPHANS.setdefault(self.owner, []).extend(conns)
            return
        for conn in conns:
            _close_quietly(conn)

    def __del__(self) -> None:
        self.close_all()


class ThreadConnections:

    def __init__(self, opener: Callable[[Path], sqlite3.Connection], limit: Optional[int] = None) -> None:
        self._opener = opener
        self._limit = limit
        self._local = threading.local()

    def _slots(self) -> Dict[str, Tuple[sqlite3.Connection, int]]:
        holder = getattr(self._local, "holder", None)
        if holder is None:
            holder = self._local.holder = _Holder()
        return holder.slots

    def held(self, path: Path) -> Optional[sqlite3.Connection]:
        held = self._slots().get(str(path))
        return held[0] if held is not None else None

    def close_this_thread(self) -> None:
        holder = getattr(self._local, "holder", None)
        if holder is not None:
            holder.close_all()

    def get(self, path: Path) -> sqlite3.Connection:
        key = str(path)
        slots = self._slots()
        try:
            inode = Path(path).stat().st_ino
        except OSError:
            inode = -1
        held = slots.get(key)
        if held is not None and held[1] == inode and inode != -1:
            return held[0]
        self.discard(path)
        conn = self._opener(Path(path))
        try:
            inode = Path(path).stat().st_ino
        except OSError:
            inode = -1
        slots[key] = (conn, inode)
        while self._limit is not None and len(slots) > self._limit:
            self.discard(Path(next(iter(slots))))
        return conn

    def discard(self, path: Path) -> None:
        held = self._slots().pop(str(path), None)
        if held is not None:
            try:
                held[0].close()
            except sqlite3.Error:
                pass

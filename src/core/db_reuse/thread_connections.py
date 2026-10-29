
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple


class ThreadConnections:

    def __init__(self, opener: Callable[[Path], sqlite3.Connection], limit: Optional[int] = None) -> None:
        self._opener = opener
        self._limit = limit
        self._local = threading.local()

    def _slots(self) -> Dict[str, Tuple[sqlite3.Connection, int]]:
        slots = getattr(self._local, "slots", None)
        if slots is None:
            slots = self._local.slots = {}
        return slots

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

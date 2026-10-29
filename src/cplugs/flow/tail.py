
from __future__ import annotations

import json
import threading
from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Tuple

from src.cplugs.flow.transcript import Fold, Scan, stamp_of

KEEP = 64


@dataclass
class _Entry:

    fold: Fold
    inode: int
    offset: int = 0
    line: int = 0


def _snapshot(scan: Scan) -> Scan:
    turns = [dict(turn, tools=dict(turn["tools"])) for turn in scan.turns]
    return replace(scan, turns=turns, spans=list(scan.spans), receipts=list(scan.receipts), launches=list(scan.launches),
                   returns=list(scan.returns), sends=list(scan.sends), spawns=list(scan.spawns), huddle=list(scan.huddle),
                   says=list(scan.says))


class TailCache:

    def __init__(self, keep: int = KEEP) -> None:
        self._keep = keep
        self._entries: "OrderedDict[Tuple[str, float, str], _Entry]" = OrderedDict()
        self._lock = threading.Lock()
        self.bytes_read = 0

    def scan(self, path: Path, lo: float, hi: float, conversation_id: str = "") -> Scan:
        key = (str(path), lo, conversation_id)
        stat = path.stat()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.inode != stat.st_ino or stat.st_size < entry.offset:
                entry = _Entry(fold=Fold(conversation_id), inode=stat.st_ino)
            if stat.st_size > entry.offset:
                self._advance(entry, path, lo, hi)
            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self._keep:
                self._entries.popitem(last=False)
            return _snapshot(entry.fold.scan)

    def _advance(self, entry: _Entry, path: Path, lo: float, hi: float) -> None:
        with path.open("rb") as handle:
            handle.seek(entry.offset)
            for raw in handle:
                if not raw.endswith(b"\n"):
                    return
                self.bytes_read += len(raw)
                text = raw.decode("utf-8", errors="replace")
                stamp = stamp_of(text)
                if stamp is not None and stamp > hi:
                    return
                entry.offset += len(raw)
                entry.line += 1
                if stamp is None or stamp < lo:
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    entry.fold.add(entry.line, record)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


CACHE = TailCache()


def stats() -> Dict[str, int]:
    return {"files": len(CACHE._entries), "bytes_read": CACHE.bytes_read}


from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from src.core.session_git.reader import read_session_git
from src.core.session_pane_facts import find_git_head
from src.models.session_git import SessionGitStatus

FLOOR_SECONDS: float = 10.0

Stamp = Tuple[Optional[int], Optional[int]]


def _mtime_ns(path: Path) -> Optional[int]:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def repo_key(directory: Path) -> Tuple[str, Optional[Path]]:
    head = find_git_head(str(directory))
    return (str(head.parent), head) if head is not None else (f"dir:{directory}", None)


def stamp_of(head: Optional[Path]) -> Stamp:
    if head is None:
        return (None, None)
    return (_mtime_ns(head), _mtime_ns(head.parent / "index"))


@dataclass
class _Entry:

    status: SessionGitStatus
    stamp: Optional[Stamp]
    spawned_at: float


class RepoCache:

    def __init__(
        self,
        reader: Callable[[Path], SessionGitStatus] = read_session_git,
        *,
        clock: Callable[[], float] = time.monotonic,
        floor: float = FLOOR_SECONDS,
    ) -> None:
        self._reader = reader
        self._clock = clock
        self._floor = floor
        self._entries: Dict[str, _Entry] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def key_of(self, directory: Path) -> str:
        return repo_key(directory)[0]

    async def get(self, directory: Path, *, force: bool = False) -> Tuple[SessionGitStatus, bool]:
        key, head = repo_key(directory)
        lock = self._locks.setdefault(key, asyncio.Lock())
        asked_at = self._clock()
        async with lock:
            entry = self._entries.get(key)
            if entry is not None:
                if entry.spawned_at >= asked_at:
                    return entry.status, False
                stamp = stamp_of(head)
                moved = entry.stamp is None or stamp != entry.stamp
                if not (force or moved) or asked_at - entry.spawned_at < self._floor:
                    return entry.status, False
            else:
                stamp = stamp_of(head)
            status = await asyncio.to_thread(self._reader, directory)
            self._entries[key] = _Entry(status, None if status.state == "unknown" else stamp, self._clock())
            return status, True

    def retain(self, keys: "set[str]") -> None:
        self._entries = {k: v for k, v in self._entries.items() if k in keys}
        self._locks = {k: v for k, v in self._locks.items() if k in keys or v.locked()}

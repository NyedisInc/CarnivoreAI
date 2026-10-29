
from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional, Set, Tuple

import structlog

logger = structlog.get_logger(__name__)

TRUST_AFTER_NS: int = 2_000_000_000
MAX_DIRS: int = 20000
_SUFFIX = ".jsonl"

_Listing = Tuple[int, Tuple[str, ...], Tuple[str, ...]]


class SubagentTreeIndex:

    def __init__(self, *, max_dirs: int = MAX_DIRS) -> None:
        self._max = max_dirs
        self._lock = threading.Lock()
        self._dirs: Dict[str, _Listing] = {}

    def _read_dir(self, path: str, now_ns: int) -> Optional[_Listing]:
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            return None
        with self._lock:
            hit = self._dirs.get(path)
        if hit is not None and hit[0] == mtime and now_ns - mtime > TRUST_AFTER_NS:
            return hit
        files: List[str] = []
        subdirs: List[str] = []
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir():
                            subdirs.append(entry.path)
                        elif entry.name.endswith(_SUFFIX) and entry.is_file():
                            files.append(entry.path)
                    except OSError:
                        continue
        except OSError as exc:
            logger.debug("subagent_tree_scandir_failed", path=path, error=str(exc))
            return None
        return (mtime, tuple(files), tuple(subdirs))

    def list_jsonl(self, root: str) -> List[str]:
        now_ns = time.time_ns()
        found: List[str] = []
        seen: Dict[str, _Listing] = {}
        pending = [root]
        while pending:
            path = pending.pop()
            listing = self._read_dir(path, now_ns)
            if listing is None:
                continue
            seen[path] = listing
            found.extend(listing[1])
            pending.extend(listing[2])
        prefix = root.rstrip(os.sep) + os.sep
        with self._lock:
            stale: Set[str] = {p for p in self._dirs if (p == root or p.startswith(prefix)) and p not in seen}
            for path in stale:
                del self._dirs[path]
            self._dirs.update(seen)
            if len(self._dirs) > self._max:
                self._dirs.clear()
        return sorted(found)

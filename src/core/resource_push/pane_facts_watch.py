
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import AbstractSet, Any, Callable, Dict, Mapping, Optional, Tuple

import structlog

from src.core.resource_push import notifier, topics
from src.core.session_pane_facts import find_git_head, read_head_branch

logger = structlog.get_logger()

Signature = Tuple[Optional[str], Optional[str], Optional[int], Optional[int], Optional[str]]


@dataclass(frozen=True)
class _Head:

    cwd: str
    path: Optional[Path]
    mtime_ns: Optional[int]
    branch: Optional[str]


def _mtime_ns(path: Path) -> Optional[int]:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


class PaneFactsWatch:

    def __init__(self, notify: Callable[[str], None] = notifier.notify) -> None:
        self._notify = notify
        self._lock = threading.Lock()
        self._last: Dict[str, Signature] = {}
        self._heads: Dict[str, _Head] = {}

    def observe(self, session_id: str, row: Mapping[str, Any]) -> bool:
        cwd = row.get("pane_current_path")
        branch = self._branch(session_id, cwd)
        signature: Signature = (
            cwd, row.get("pane_current_command"), row.get("pane_width"), row.get("pane_height"), branch,
        )
        with self._lock:
            previous = self._last.get(session_id)
            self._last[session_id] = signature
        if previous is None or previous == signature:
            return False
        self._notify(topics.keyed(topics.PANE_FACTS, session_id))
        logger.debug("pane_facts_changed", session_id=session_id)
        return True

    def retain(self, session_ids: AbstractSet[str]) -> None:
        with self._lock:
            self._last = {k: v for k, v in self._last.items() if k in session_ids}
            self._heads = {k: v for k, v in self._heads.items() if k in session_ids}

    def _branch(self, session_id: str, cwd: Optional[str]) -> Optional[str]:
        if not cwd:
            return None
        with self._lock:
            head = self._heads.get(session_id)
        if head is None or head.cwd != cwd:
            path = find_git_head(cwd)
            head = _Head(cwd, path, _mtime_ns(path) if path else None,
                         read_head_branch(path) if path else None)
        elif head.path is not None:
            mtime = _mtime_ns(head.path)
            if mtime != head.mtime_ns:
                head = _Head(cwd, head.path, mtime, read_head_branch(head.path))
        with self._lock:
            self._heads[session_id] = head
        return head.branch

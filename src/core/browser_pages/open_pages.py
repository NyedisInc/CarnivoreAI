
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import structlog

from src.core import resource_push, row_looks
from src.core.browser_pages import store
from src.core.resource_push.topics import BROWSER_PAGES

MAX_PAGES = 16
MAX_TITLE = 120


@dataclass
class OpenPage:

    id: str
    key: str
    frame: str
    title: str
    opened_at: float
    ref: Optional[Dict[str, object]] = None
    src: Optional[str] = None
    seq: int = field(default=0)


logger = structlog.get_logger(__name__)

_lock = threading.Lock()
_pages: List[OpenPage] = []
_clock = 0
_file: Optional[Path] = None


def _persist_locked() -> None:
    if _file is not None:
        store.save(_file, [asdict(p) for p in _pages])


def configure(state_directory: Optional[Path]) -> None:
    """Point the list at its file in the state directory and load what a previous run left (call once at startup).

    Inputs: state_directory (the app state dir; None detaches persistence). Output: None. Rows come back in stored
    order with their ids, keys and targets; a row whose target is gone (a deleted artifact, the Task Manager off) is kept and
    listed with ``src`` None, as for a row opened this run (``browser_open_routes._page_info``).
    """
    global _file, _clock
    with _lock:
        _file = None if state_directory is None else store.path_in(state_directory)
        _pages.clear()
        _clock = 0
        if _file is None:
            return
        for row in store.load(_file)[-MAX_PAGES:]:
            _pages.append(OpenPage(**{k: row.get(k) for k in OpenPage.__dataclass_fields__ if k in row}))
        _clock = max((p.seq for p in _pages), default=0)
    logger.info("browser_pages_restored", count=len(_pages))


def page_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def open_page(key: str, frame: str, title: str, *, ref: Optional[Dict[str, object]] = None, src: Optional[str] = None) -> OpenPage:
    global _clock
    with _lock:
        _clock += 1
        found = next((p for p in _pages if p.key == key), None)
        if found is None:
            found = OpenPage(page_id(key), key, frame, title[:MAX_TITLE], time.time(), ref, src)
            _pages.append(found)
            if len(_pages) > MAX_PAGES:
                _pages.remove(min((p for p in _pages if p is not found), key=lambda p: p.seq))
        else:
            found.title, found.ref, found.src, found.opened_at = title[:MAX_TITLE], ref, src, time.time()
        found.seq = _clock
        stored = found
        _persist_locked()
    resource_push.notify(BROWSER_PAGES)
    return stored


def listing() -> List[OpenPage]:
    with _lock:
        return [OpenPage(p.id, p.key, p.frame, p.title, p.opened_at, p.ref, p.src, p.seq) for p in _pages]


def get(page: str) -> Optional[OpenPage]:
    return next((p for p in listing() if p.id == page), None)


def close(page: str) -> bool:
    with _lock:
        kept = [p for p in _pages if p.id != page]
        removed = len(kept) != len(_pages)
        _pages[:] = kept
        if removed:
            _persist_locked()
    if removed:
        resource_push.notify(BROWSER_PAGES)
        row_looks.forget(page)
    return removed


def reset_for_test() -> None:
    global _clock
    global _file
    with _lock:
        _pages.clear()
        _clock = 0
        _file = None


__all__ = ["MAX_PAGES", "MAX_TITLE", "OpenPage", "close", "configure", "get", "listing", "open_page", "page_id", "reset_for_test"]

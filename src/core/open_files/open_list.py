"""
HELD IN MEMORY AND PERSISTED: every change is written to ``open_files.json`` in the state directory (``store.py``) at
the one mutation point below, and :func:`configure` reloads it once at startup, so a restart brings each row back with
the same id and order. No database. THE ONE WRITER of the ``open_files`` topic: every open, reuse and close names it
(``resource_push.notify``), so every open window re-reads ``GET /api/v1/files/open`` once (PUSH, NOT PULL).
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import List, Optional, Tuple

import structlog

from src.core import resource_push, row_looks
from src.core.open_files import store
from src.core.resource_push.topics import OPEN_FILES

MAX_FILES = 64
MAX_TITLE = 120

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class OpenFile:

    id: str
    kind: str
    root: str
    path: str
    session_uuid: str
    title: str
    opened_at: float
    seq: int = 0


_lock = threading.Lock()
_files: List[OpenFile] = []
_clock = 0
_file: Optional[Path] = None


def _persist_locked() -> None:
    if _file is not None:
        store.save(_file, [asdict(f) for f in _files])


def configure(state_directory: Optional[Path]) -> None:
    """Point the list at its file in the state directory and load what a previous run left (call once at startup).
    """
    global _file, _clock
    with _lock:
        _file = None if state_directory is None else store.path_in(state_directory)
        _files.clear()
        _clock = 0
        if _file is None:
            return
        for row in store.load(_file)[-MAX_FILES:]:
            _files.append(OpenFile(**{k: row[k] for k in OpenFile.__dataclass_fields__ if k in row}))
        _clock = max((f.seq for f in _files), default=0)
    logger.info("open_files_restored", count=len(_files))


def new_id() -> str:
    return secrets.token_hex(8)


def title_for(path: str) -> str:
    return (os.path.basename(path.rstrip("/")) or path)[:MAX_TITLE]


def open_file(kind: str, root: str, path: str, session_uuid: str) -> Tuple[OpenFile, bool]:
    global _clock
    with _lock:
        _clock += 1
        found = next((f for f in _files if (f.kind, f.root, f.path, f.session_uuid) == (kind, root, path, session_uuid)), None)
        if found is None:
            stored = OpenFile(new_id(), kind, root, path, session_uuid, title_for(path), time.time(), _clock)
            _files.append(stored)
            if len(_files) > MAX_FILES:
                _files.remove(min((f for f in _files if f is not stored), key=lambda f: f.seq))
        else:
            stored = replace(found, opened_at=time.time(), seq=_clock)
            _files[_files.index(found)] = stored
        _persist_locked()
    resource_push.notify(OPEN_FILES)
    return stored, found is not None


def listing(session_uuid: Optional[str] = None) -> List[OpenFile]:
    with _lock:
        return [f for f in _files if session_uuid is None or f.session_uuid == session_uuid]


def get(file_id: str) -> Optional[OpenFile]:
    return next((f for f in listing() if f.id == file_id), None)


def close(file_id: str) -> bool:
    with _lock:
        kept = [f for f in _files if f.id != file_id]
        removed = len(kept) != len(_files)
        _files[:] = kept
        if removed:
            _persist_locked()
    if removed:
        resource_push.notify(OPEN_FILES)
        row_looks.forget(file_id)
    return removed


def reset_for_test() -> None:
    global _clock, _file
    with _lock:
        _files.clear()
        _clock = 0
        _file = None


__all__ = ["MAX_FILES", "MAX_TITLE", "OpenFile", "close", "configure", "get", "listing", "new_id", "open_file",
           "reset_for_test", "title_for"]

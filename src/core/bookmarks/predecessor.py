
from __future__ import annotations

import mmap
from pathlib import Path
from typing import Optional, Sequence

import structlog

logger = structlog.get_logger()

MAX_FILES = 400


def _holds_uuid(path: Path, needle: bytes) -> bool:
    try:
        with path.open("rb") as stream:
            if path.stat().st_size == 0:
                return False
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as view:
                return view.find(needle) != -1
    except (OSError, ValueError) as exc:
        logger.debug("predecessor_file_unreadable", path=str(path), error=str(exc))
        return False


def find_holder(current: Path, uuid: str, roots: Optional[Sequence[Path]] = None) -> Optional[Path]:
    needle = f'"uuid":"{uuid}"'.encode()
    if roots is None:
        from src.core.bookmarks import locate

        roots = locate._roots()
    folders = [current.parent] + [d for root in roots if root.is_dir() for d in sorted(root.iterdir())
                                  if d.is_dir() and d != current.parent]
    checked = 0
    for folder in folders:
        try:
            files = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError as exc:
            logger.debug("predecessor_folder_unreadable", folder=str(folder), error=str(exc))
            continue
        for candidate in files:
            if candidate == current:
                continue
            checked += 1
            if checked > MAX_FILES:
                return None
            if _holds_uuid(candidate, needle):
                return candidate
    return None

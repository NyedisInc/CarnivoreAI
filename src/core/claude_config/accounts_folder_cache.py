
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

ACCOUNTS_DIR_ENV = "CARNIVORE_ACCOUNTS_DIR"

MAX_ENTRIES = 64

_Sig = Tuple[int, int, int, int]

_lock = threading.Lock()
_listings: "OrderedDict[Tuple[str, str], Tuple[_Sig, Tuple[Path, ...]]]" = OrderedDict()


def accounts_root() -> Path:
    override = os.environ.get(ACCOUNTS_DIR_ENV, "").strip()
    return Path(override).expanduser() if override else Path.home() / ".carnivore" / "accounts"


def clear() -> None:
    with _lock:
        _listings.clear()


def _signature(root: Path) -> Optional[_Sig]:
    try:
        st = os.stat(root)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_ctime_ns, st.st_ino, st.st_dev)


def _list_names(root: Path, pattern: str) -> Optional[Tuple[Path, ...]]:
    try:
        return tuple(sorted(root.glob(pattern)))
    except OSError as exc:
        logger.debug("accounts_folder_unreadable", root=str(root), error=str(exc))
        return None


def _live_dirs(names: Tuple[Path, ...], keep: Optional[Callable[[str], bool]]) -> List[Path]:
    try:
        return [p for p in names if p.is_dir() and (keep is None or keep(p.name))]
    except OSError as exc:
        logger.debug("accounts_folder_entry_unreadable", error=str(exc))
        return []


def listed_dirs(pattern: str, keep: Optional[Callable[[str], bool]] = None, root: Optional[Path] = None) -> List[Path]:
    folder = root if root is not None else accounts_root()
    key = (str(folder), pattern)
    sig = _signature(folder)
    if sig is None:
        with _lock:
            _listings.pop(key, None)
        return []
    with _lock:
        held = _listings.get(key)
        if held is not None and held[0] == sig:
            _listings.move_to_end(key)
            return _live_dirs(held[1], keep)
    found = _list_names(folder, pattern)
    if found is None:
        return []
    if _signature(folder) == sig:
        with _lock:
            _listings[key] = (sig, found)
            _listings.move_to_end(key)
            while len(_listings) > MAX_ENTRIES:
                _listings.popitem(last=False)
    return _live_dirs(found, keep)

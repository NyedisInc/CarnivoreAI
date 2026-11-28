
from __future__ import annotations

import json
import os
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

MARKER_PREFIX, MARKER_SUFFIX = ".moved-to-", ".json"
FILES_DIR_NAME = "files"


def nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def is_bookkeeping(name: str) -> bool:
    return name.startswith(".")


def marker_name(new_id: str) -> str:
    return f"{MARKER_PREFIX}{new_id}{MARKER_SUFFIX}"


def moved_list(marker: Path) -> Optional[Dict[str, str]]:
    try:
        with open(marker, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("cplug_renamed_files_marker_unreadable", marker=str(marker), error_type=type(exc).__name__)
        return None
    files = data.get("files") if isinstance(data, dict) else None
    return {str(k): str(v) for k, v in files.items()} if isinstance(files, dict) else None


@lru_cache(maxsize=8)
def _handed_over_cached(marker: str, _stamp: Tuple[int, int]) -> FrozenSet[str]:
    return frozenset(nfc(rel) for rel in moved_list(Path(marker)) or ())


def handed_over(previous_files: Path, new_files: Path, path: Path) -> bool:
    marker = previous_files / marker_name(new_files.parent.name)
    try:
        st = os.stat(marker)
        rel = path.relative_to(previous_files).as_posix()
    except (OSError, ValueError):
        return False
    if not new_files.is_dir():
        return False
    return nfc(rel) in _handed_over_cached(str(marker), (st.st_mtime_ns, st.st_size))


def _regular_file(path: Path) -> bool:
    return not path.is_symlink() and path.is_file()


def servable(new_files: Path, previous_files: Optional[Path], path: Path) -> bool:
    if previous_files is None:
        return True
    try:
        rel = path.relative_to(previous_files)
    except ValueError:
        return True
    return not _regular_file(new_files / rel) and not handed_over(previous_files, new_files, path)


def _regular_files(folder: Path) -> List[Path]:
    if folder.is_symlink() or not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if not is_bookkeeping(p.name) and _regular_file(p))


def merged_item_files(new_files: Path, previous_files: Optional[Path], item: str) -> List[Path]:
    out = _regular_files(new_files / item)
    if previous_files is None:
        return out
    names = {nfc(p.name) for p in out}
    return out + [p for p in _regular_files(previous_files / item)
                  if nfc(p.name) not in names and servable(new_files, previous_files, p)]

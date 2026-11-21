
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from src.core.pack.transport.history_objects import HistoryScanFailed

MAX_POINTER_BYTES = 1024
_VERSION_LINE = b"version https://git-lfs.github.com/spec/v1\n"
_OID_LINE = re.compile(rb"^oid sha256:([0-9a-f]{64})$", re.MULTILINE)


def pointer_oid(content: bytes) -> Optional[str]:
    if len(content) >= MAX_POINTER_BYTES or not content.startswith(_VERSION_LINE):
        return None
    match = _OID_LINE.search(content)
    return match.group(1).decode("ascii") if match else None


def object_path(git_dir: str, oid: str) -> Path:
    return Path(git_dir) / "lfs" / "objects" / oid[0:2] / oid[2:4] / oid


def object_sizes(git_dir: str, names: Dict[str, str]) -> Dict[str, int]:
    sizes: Dict[str, int] = {}
    missing: List[str] = []
    for oid, name in names.items():
        path = object_path(git_dir, oid)
        try:
            if path.is_symlink() or not path.is_file():
                missing.append(f"{name} (lfs object missing)")
                continue
            sizes[oid] = path.stat().st_size
        except OSError:
            missing.append(f"{name} (lfs object missing)")
    if missing:
        raise HistoryScanFailed("lfs_object_missing", missing)
    return sizes

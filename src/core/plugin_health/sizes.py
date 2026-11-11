
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Collection, List

import structlog

from src.core.plugin_health.model import OrphanData

logger = structlog.get_logger()

_UUID = re.compile(r"^[0-9a-f]{32}$")
HOST_FOLDERS = frozenset({"profiles", "retired-profiles"})
BACKUP_FOLDER_PREFIX = "migration-backup-"
MAX_FILES_COUNTED = 100_000


def dir_bytes(path: Path) -> int:
    total, seen = 0, 0
    stack = [str(path)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    seen += 1
                    if seen > MAX_FILES_COUNTED:
                        return total
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
        except OSError as exc:
            logger.debug("plugin_health_size_unreadable", error_type=type(exc).__name__)
    return total


def orphan_folders(plugin_root: Path, owned_keys: Collection[str]) -> List[OrphanData]:
    found: List[OrphanData] = []
    try:
        with os.scandir(plugin_root) as entries:
            names = sorted(e.name for e in entries if e.is_dir(follow_symlinks=False))
    except OSError:
        return found
    for name in names:
        if name.startswith((".", BACKUP_FOLDER_PREFIX)) or name in HOST_FOLDERS or name in owned_keys:
            continue
        found.append(OrphanData(name, dir_bytes(plugin_root / name)))
    return found

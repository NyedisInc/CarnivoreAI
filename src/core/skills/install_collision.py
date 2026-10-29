
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional

import structlog

from src.core.skills.digest import hash_file
from src.core.skills.install_types import FileDelta
from src.core.skills.records import read_sidecar

logger = structlog.get_logger()


def _tree_index(directory: Path) -> dict[str, tuple[str, int]]:
    index: dict[str, tuple[str, int]] = {}
    for parent, _dir_names, file_names in os.walk(directory, followlinks=False):
        for file_name in file_names:
            absolute = Path(parent) / file_name
            if absolute.is_symlink():
                continue
            try:
                hex_digest, size = hash_file(absolute)
            except OSError as exc:
                logger.warning(
                    "skill_delta_entry_unreadable",
                    path=str(absolute),
                    error=str(exc),
                )
                continue
            index[absolute.relative_to(directory).as_posix()] = (hex_digest, size)
    return index


def compute_delta(existing: Path, staged: Path) -> FileDelta:
    before = _tree_index(existing)
    after = _tree_index(staged)
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(
        path for path in set(before) & set(after) if before[path][0] != after[path][0]
    )
    bytes_before = sum(size for _hex, size in before.values())
    bytes_after = sum(size for _hex, size in after.values())
    return FileDelta(
        against=str(existing),
        added=len(added),
        changed=len(changed),
        removed=len(removed),
        byte_delta=bytes_after - bytes_before,
    )


def is_managed_by(directory: Path, item_id: str) -> bool:
    record = read_sidecar(directory)
    if record is None:
        return False
    return f"{record.publisher}/{record.name}" == item_id


def listing_collision(name: str, discovery_listing: Iterable[str]) -> Optional[str]:
    for entry in discovery_listing:
        if entry.startswith("."):
            continue
        if entry == name:
            return entry
    return None

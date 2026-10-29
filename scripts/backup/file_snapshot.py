
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, Iterator, Tuple

import structlog

from scripts.backup.db_snapshot import file_sha256

logger = structlog.get_logger()

FileFacts = Dict[str, object]


def iter_files(root: Path) -> Iterator[Tuple[str, Path]]:
    if not root.is_dir():
        return
    for current, dirs, names in os.walk(root):
        dirs.sort()
        for name in sorted(names):
            path = Path(current) / name
            if path.is_file() and not path.is_symlink():
                yield path.relative_to(root).as_posix(), path


def describe_file(path: Path) -> FileFacts:
    return {"bytes": path.stat().st_size, "sha256": file_sha256(path)}


def copy_file(source: Path, dest: Path) -> FileFacts:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return describe_file(dest)


def copy_tree(source: Path, dest: Path) -> Dict[str, FileFacts]:
    out = {rel: copy_file(path, dest / rel) for rel, path in iter_files(source)}
    logger.info("phase_backup_tree_copied", tree=source.name, files=len(out))
    return out


def describe_tree(root: Path) -> Dict[str, FileFacts]:
    return {rel: describe_file(path) for rel, path in iter_files(root)}


def diff_files(expected: Dict[str, FileFacts], actual: Dict[str, FileFacts]) -> Tuple[list, list, list]:
    removed = sorted(set(expected) - set(actual))
    added = sorted(set(actual) - set(expected))
    changed = sorted(p for p in set(expected) & set(actual) if expected[p]["sha256"] != actual[p]["sha256"])
    return removed, changed, added

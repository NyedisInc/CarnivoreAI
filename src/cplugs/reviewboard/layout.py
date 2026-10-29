
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator, Optional

from src.cplugs.sdk import task_folders

SLUG = re.compile(r"[0-9]{8}-[a-z0-9-]{1,48}")


def _inside(path: Path, root: Path) -> bool:
    real, base = Path(os.path.realpath(path)), Path(os.path.realpath(root))
    return base in real.parents


def board_dir(root: Path, slug: str) -> Optional[Path]:
    if not SLUG.fullmatch(slug or ""):
        return None
    flat = root / slug
    if task_folders.is_real_dir(flat):
        return flat
    for folder in sorted(root.glob(f"*/*/{task_folders.BOARDS}/{slug}")):
        task = folder.parent.parent
        if (task_folders.is_real_dir(folder) and task_folders.is_real_dir(folder.parent) and task_folders.task_item_of(task) is not None
                and task_folders.is_project_folder(task.parent) and _inside(folder, root)):
            return folder
    return None


def nested_entries(root: Path) -> Iterator[Path]:
    for task in task_folders.task_folders(root):
        boards = task / task_folders.BOARDS
        if not task_folders.is_real_dir(boards):
            continue
        try:
            entries = sorted(boards.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        yield from (e for e in entries if not e.name.startswith("."))


def is_container(entry: Path) -> bool:
    return task_folders.is_project_folder(entry)


__all__ = ["SLUG", "board_dir", "is_container", "nested_entries"]

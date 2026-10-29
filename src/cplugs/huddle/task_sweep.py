
from __future__ import annotations

import re
import sqlite3
import stat
import time
from contextlib import closing
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Optional, Set

import structlog

from src.cplugs.huddle import files, store_identity, task_files
from src.cplugs.sdk import CplugStorage, task_folders

logger = structlog.get_logger()

SWEPT_KINDS = (task_folders.PASTES, task_folders.ARTIFACTS)
STORED_NAME = re.compile(rf"^(?:{re.escape(files.ASIDE_PREFIX)})?[0-9a-f]{{8}}-[A-Za-z0-9_][A-Za-z0-9._-]*$")
STORE_MODE = 0o600


class Swept(NamedTuple):

    item_id: int
    list_key: str
    store_id: Optional[str]
    folder: Path


def referenced_names(conn: sqlite3.Connection) -> Set[str]:
    if not files.has_messages(conn):
        return set()
    rows = conn.execute(f"SELECT parts FROM work_messages WHERE {files.PARTS_SQL}").fetchall()
    return {Path(e["path"]).name for r in rows for e in files.entries_of(r["parts"]) if isinstance(e.get("path"), str)}


def known_lists(conn: sqlite3.Connection) -> Dict[int, str]:
    return {r["id"]: r["list_key"] for r in conn.execute("SELECT id, list_key FROM work_items")}


def _swept_folders(root: Path) -> Iterator[Swept]:
    root_real = root.resolve()
    for task in task_folders.task_folders(root):
        marker = task_folders.read_marker(task, task_folders.TASK_MARKER) or {}
        item_id, list_key = task_folders.task_item_of(task), marker.get("list")
        if item_id is None or not isinstance(list_key, str):
            continue
        for kind in SWEPT_KINDS:
            folder = task / kind
            if task_folders.is_real_dir(folder) and task_folders.within(root_real, folder):
                yield Swept(item_id, list_key, task_folders.task_store_of(task), folder)


def _candidates(folder: Path) -> List[Path]:
    try:
        return sorted(p for p in folder.iterdir() if STORED_NAME.match(p.name))
    except OSError as exc:
        logger.warning("task_manager_task_folder_unreadable", folder=str(folder), error=type(exc).__name__)
        return []


def _sweepable(path: Path, keep: Set[str], at: float, age_s: float) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != STORE_MODE:
        return False
    if path.name.startswith(files.ASIDE_PREFIX):
        return path.name[len(files.ASIDE_PREFIX):] not in keep and at - info.st_mtime >= files.ASIDE_GRACE_S
    return path.name not in keep and at - info.st_mtime >= age_s


def _unlink(path: Path) -> int:
    try:
        path.unlink()
    except FileNotFoundError:
        return 0
    except OSError as exc:
        logger.warning("task_manager_task_file_unlink_failed", name=path.name, error=type(exc).__name__)
        return 0
    return 1


def sweep_task_folders(storage: CplugStorage, root: Path, now: Optional[float] = None, age_s: float = files.ORPHAN_AGE_S) -> int:
    if not storage.db_path.exists():
        return 0
    found = [(swept, path) for swept in _swept_folders(root) for path in _candidates(swept.folder)]
    if not found:
        return 0
    at = time.time() if now is None else now
    removed = 0
    with closing(storage.connect(True)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            keep, ours, mine = referenced_names(conn), known_lists(conn), store_identity.read(conn)
            removed = sum(_unlink(path) for swept, path in found
                          if mine is not None and swept.store_id == mine and ours.get(swept.item_id) == swept.list_key and _sweepable(path, keep, at, age_s))
        finally:
            conn.rollback()
    if removed:
        logger.info("task_manager_task_folder_files_swept", removed=removed)
    return removed


def sweep_all(storage: CplugStorage, now: Optional[float] = None, age_s: float = files.ORPHAN_AGE_S) -> int:
    removed = files.sweep_orphans(storage, now, age_s)
    root = task_files.root_now()
    return removed + (sweep_task_folders(storage, root, now, age_s) if root is not None else 0)


__all__ = ["STORED_NAME", "STORE_MODE", "SWEPT_KINDS", "referenced_names", "sweep_all", "sweep_task_folders"]

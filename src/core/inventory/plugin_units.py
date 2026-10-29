
from __future__ import annotations

import errno
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

import structlog

from src.cplugs.sdk import task_folders

logger = structlog.get_logger()

BOARD_SIDECAR = "sidecar.json"
MAX_BOARD_DEPTH = 4
MAX_SIDECAR_BYTES = 16 * 1024 * 1024
MARKERS: Tuple[str, ...] = (task_folders.PROJECT_MARKER, task_folders.TASK_MARKER)


@dataclass(frozen=True)
class Unit:

    rel: str
    is_dir: bool

    def as_json(self) -> Dict[str, Any]:
        return {"rel": self.rel, "dir": self.is_dir}


@dataclass(frozen=True)
class TaskLink:

    item_id: Optional[int] = None
    list_key: Optional[str] = None
    computer: Optional[str] = None


@dataclass(frozen=True)
class Board:

    rel: str
    slug: str
    link: TaskLink


@dataclass(frozen=True)
class OwnerKeys:

    kind: str
    session_uuids: FrozenSet[str] = frozenset()
    project_keys: FrozenSet[str] = frozenset()
    item_ids: FrozenSet[int] = frozenset()
    list_key: Optional[str] = None
    known_item_ids: FrozenSet[int] = frozenset()
    here: Optional[str] = None

    def _local_item(self, link: TaskLink) -> Optional[int]:
        if link.item_id is None:
            return None
        return link.item_id if not link.computer or not self.here or link.computer == self.here else None

    def carries_link(self, link: TaskLink) -> bool:
        if self.kind != "project":
            return False
        item = self._local_item(link)
        if item is not None and item in self.known_item_ids | self.item_ids:
            return item in self.item_ids
        return link.list_key is not None and link.list_key == self.list_key


def _regular(path: Path) -> bool:
    """Whether ``path`` is a regular file and not a symlink. Output: bool."""
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _sidecar_task(folder: Path) -> Tuple[Optional[int], Optional[str]]:
    path = folder / BOARD_SIDECAR
    try:
        if not _regular(path) or path.stat().st_size > MAX_SIDECAR_BYTES:
            return None, None
        task = json.loads(path.read_text(encoding="utf-8")).get("task")
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("plugin_unit_sidecar_unreadable", path=str(path), error=type(exc).__name__)
        return None, None
    if not isinstance(task, dict):
        return None, None
    value, computer = task.get("item_id"), task.get("computer")
    item = value if isinstance(value, int) and not isinstance(value, bool) else None
    return item, (computer if isinstance(computer, str) and computer else None)


def _link_of(root: Path, folder: Path) -> TaskLink:
    item, computer = _sidecar_task(folder)
    list_key: Optional[str] = None
    parent = folder.parent
    while parent != root and root in parent.parents:
        if item is None:
            item = task_folders.task_item_of(parent)
        list_key = list_key or task_folders.project_list_of(parent)
        parent = parent.parent
    return TaskLink(item, list_key, computer)


def find_boards(root: Path, problems: Optional[List[str]] = None) -> List[Board]:
    found: List[Board] = []
    stack: List[Tuple[Path, int]] = [(root, 0)]
    while stack:
        folder, depth = stack.pop()
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError as exc:
            logger.warning("plugin_unit_folder_unreadable", path=str(folder), error=type(exc).__name__)
            if problems is not None and not isinstance(exc, FileNotFoundError):
                problems.append(unlistable_sentence(folder, exc))
            continue
        if folder != root and any(e.name == BOARD_SIDECAR for e in entries):
            found.append(Board(folder.relative_to(root).as_posix(), folder.name, _link_of(root, folder)))
            continue
        if depth < MAX_BOARD_DEPTH:
            stack += [(Path(e.path), depth + 1) for e in entries if not e.name.startswith(".") and e.is_dir(follow_symlinks=False)]
    return sorted(found, key=lambda b: b.rel)


def unlistable_sentence(folder: Path, exc: OSError) -> str:
    why = "only in iCloud, not on this disk" if exc.errno == errno.EDEADLK else f"not readable ({type(exc).__name__})"
    return f"{folder} is {why}, so what it holds cannot be listed for the crate"


def slug_index(boards: Iterable[Board]) -> Dict[str, List[TaskLink]]:
    out: Dict[str, List[TaskLink]] = {}
    for board in boards:
        out.setdefault(board.slug, []).append(board.link)
    return out


def _markers_above(root: Path, rel: str) -> List[Unit]:
    out: List[Unit] = []
    parts = rel.split("/")[:-1]
    for depth in range(1, len(parts) + 1):
        folder = root.joinpath(*parts[:depth])
        out += [Unit("/".join(parts[:depth] + [name]), False) for name in MARKERS if _regular(folder / name)]
    return out


def _top_entries(root: Path) -> List[os.DirEntry]:
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError as exc:
        logger.warning("plugin_unit_folder_unreadable", path=str(root), error=type(exc).__name__)
        return []
    return [e for e in entries if not e.name.startswith(".") and not e.is_symlink() and (e.is_dir(follow_symlinks=False) or e.is_file(follow_symlinks=False))]


def task_units(root: Path, siblings: Dict[str, List[TaskLink]], owner: OwnerKeys,
               problems: Optional[List[str]] = None) -> Tuple[List[Unit], int]:
    """The units of a ``task_item_id`` store the scope carries, and how many it leaves out.

    Inputs: root (the store); siblings (board links by slug across the plugin's task-scoped stores, for the draft files); owner;
      problems (collects a sentence per folder that could not be listed, see :func:`find_boards`).
    Output: (units sorted by rel, out of scope count). A store with boards in it is cut into boards; one without is cut into the
      top-level files named for a board.
    Example: task_units(Path("/boards"), {}, OwnerKeys("project", item_ids=frozenset({592}))) -> ([Unit("a-592/boards/20261013-x", True)], 3)
    """
    boards = find_boards(root, problems)
    units: Dict[str, Unit] = {}
    out_of_scope = 0
    if boards:
        for board in boards:
            if owner.carries_link(board.link):
                units[board.rel] = Unit(board.rel, True)
                units.update({u.rel: u for u in _markers_above(root, board.rel)})
            else:
                out_of_scope += 1
    else:
        for entry in _top_entries(root):
            links = siblings.get(entry.name.split(".")[0], []) if entry.is_file(follow_symlinks=False) else []
            if any(owner.carries_link(link) for link in links):
                units[entry.name] = Unit(entry.name, False)
            else:
                out_of_scope += 1
    return [units[k] for k in sorted(units)], out_of_scope


def owner_units(root: Path, keys: Set[str]) -> Tuple[List[Unit], int]:
    units: List[Unit] = []
    out_of_scope = 0
    for entry in _top_entries(root):
        if entry.name in keys or entry.name.split(".")[0] in keys:
            units.append(Unit(entry.name, entry.is_dir(follow_symlinks=False)))
        else:
            out_of_scope += 1
    return units, out_of_scope

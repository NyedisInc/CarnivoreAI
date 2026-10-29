"""The Task Manager folder layout: ``<root>/<project>/<task>/`` with ``pastes/``, ``artifacts/`` and ``boards/`` inside (issue #1733).

NEVER MOVED. A folder is made once and never renamed or moved. The record is the folder itself: its name ends in ``-<id>`` and it holds
a small JSON marker (:data:`PROJECT_MARKER`, :data:`TASK_MARKER`) naming that id. :func:`find_task` finds an item's folder by id
wherever it was made, so a renamed task, a renamed project or an item moved to another list keeps writing to its first folder.
Item ids are never reused (``AUTOINCREMENT``), so an id names one task for good. No database column is involved.

SAFETY. ``root`` is a folder the caller has already checked (the review board's ``root.check_root``: absolute, no symlink, the
``.boards-root`` marker, inside a git checkout). Nothing here follows a symlink: a folder that is one is never used, and a marker is
read only as a regular file. ``pastes/`` and ``artifacts/`` get a ``.gitignore`` of ``*`` when made, because the root sits in a git
checkout and a paste may be a screenshot of anything. Nothing here deletes.
"""

from __future__ import annotations

import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

ROOT_MARKER = ".boards-root"
PROJECT_MARKER = ".tm-project"
TASK_MARKER = ".tm-task"
NO_PROJECT = "no-project"
PASTES = "pastes"
ARTIFACTS = "artifacts"
BOARDS = "boards"
KINDS = (PASTES, ARTIFACTS, BOARDS)
GIT_IGNORED_KINDS = frozenset({PASTES, ARTIFACTS})
PRIVATE_KINDS = frozenset({PASTES, ARTIFACTS})
Before = Callable[[str, Path, Optional[Dict[str, Any]]], None]
MAX_SLUG = 48
PROJECT_FALLBACK = "project"
TASK_FALLBACK = "task"
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_PROJECT_KEY = re.compile(r"^[0-9]+$")


def slugify(text: Optional[str], fallback: str) -> str:
    slug = _NON_SLUG.sub("-", (text or "").lower()).strip("-")
    if len(slug) > MAX_SLUG:
        cut = slug[:MAX_SLUG + 1]
        slug = cut.rsplit("-", 1)[0] if "-" in cut[MAX_SLUG // 2:] else slug[:MAX_SLUG]
    return slug.rstrip("-") or fallback


def is_project_key(list_key: str) -> bool:
    return bool(_PROJECT_KEY.match(list_key or ""))


def project_folder_name(list_key: str, project_name: Optional[str]) -> str:
    if not is_project_key(list_key):
        return NO_PROJECT
    return f"{slugify(project_name, PROJECT_FALLBACK)}-{int(list_key)}"


def task_folder_name(item_id: int, title: Optional[str]) -> str:
    return f"{slugify(title, TASK_FALLBACK)}-{int(item_id)}"


def is_real_dir(path: Path) -> bool:
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def read_marker(folder: Path, name: str) -> Optional[Dict[str, Any]]:
    path = folder / name
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_once(path: Path, data: bytes) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _write_marker(folder: Path, name: str, value: Dict[str, Any]) -> None:
    _write_once(folder / name, (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))


def _make_dir(path: Path, mode: int = 0o755) -> None:
    try:
        path.mkdir(mode=mode)
    except FileExistsError:
        pass
    if not is_real_dir(path):
        raise NotADirectoryError(f"{path} is not a real folder")
    if mode != 0o755:
        path.chmod(mode)


def ensure_root(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _make_dir(path, 0o700)
    _write_once(path / ROOT_MARKER, b"boards root: the review boards plugin writes boards under this folder\n")
    return path


def project_list_of(folder: Path) -> Optional[str]:
    marker = read_marker(folder, PROJECT_MARKER)
    value = marker.get("list") if marker else None
    return str(value) if isinstance(value, (str, int)) else None


def is_project_folder(folder: Path) -> bool:
    return is_real_dir(folder) and read_marker(folder, PROJECT_MARKER) is not None


def task_item_of(folder: Path) -> Optional[int]:
    if not is_real_dir(folder):
        return None
    marker = read_marker(folder, TASK_MARKER)
    value = marker.get("item_id") if marker else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def find_project(root: Path, list_key: str) -> Optional[Path]:
    if not is_project_key(list_key):
        folder = root / NO_PROJECT
        return folder if is_project_folder(folder) else None
    for folder in sorted(root.glob(f"*-{int(list_key)}")):
        if is_project_folder(folder) and project_list_of(folder) == str(int(list_key)):
            return folder
    return None


def find_task(root: Path, item_id: int) -> Optional[Path]:
    for folder in sorted(root.glob(f"*/*-{int(item_id)}")):
        if is_project_folder(folder.parent) and task_item_of(folder) == int(item_id):
            return folder
    return None


def _announce(before: Optional[Before], kind: str, path: Path, match: Optional[Dict[str, Any]]) -> None:
    if before is not None and not os.path.lexists(path):
        before(kind, path, match)


def ensure_project(root: Path, list_key: str, project_name: Optional[str], before: Optional[Before] = None) -> Path:
    found = find_project(root, list_key)
    if found is not None:
        return found
    folder = root / project_folder_name(list_key, project_name)
    is_project = is_project_key(list_key)
    _announce(before, "dir", folder, None)
    _announce(before, "marker", folder / PROJECT_MARKER, {"list": str(int(list_key)) if is_project else None})
    _make_dir(folder)
    _write_marker(folder, PROJECT_MARKER, {"list": str(int(list_key)) if is_project else None,
                                           "name": project_name if is_project else None, "created_at": _now()})
    return folder


def ensure_task(root: Path, item_id: int, list_key: str, project_name: Optional[str], title: Optional[str],
                before: Optional[Before] = None) -> Path:
    found = find_task(root, item_id)
    if found is not None:
        return found
    folder = ensure_project(root, list_key, project_name, before) / task_folder_name(item_id, title)
    _announce(before, "dir", folder, None)
    _announce(before, "marker", folder / TASK_MARKER, {"item_id": int(item_id), "list": list_key})
    _make_dir(folder)
    _write_marker(folder, TASK_MARKER, {"item_id": int(item_id), "list": list_key, "title": title, "created_at": _now()})
    return folder


def kind_dir(task: Path, kind: str, create: bool = True, before: Optional[Before] = None) -> Path:
    if kind not in KINDS:
        raise ValueError(f"unknown task folder kind {kind!r}")
    folder = task / kind
    if create:
        _announce(before, "dir", folder, None)
        _make_dir(folder, 0o700 if kind in PRIVATE_KINDS else 0o755)
        if kind in GIT_IGNORED_KINDS:
            _write_once(folder / ".gitignore", b"*\n")
    return folder


def task_folders(root: Path) -> Iterator[Path]:
    try:
        projects = sorted(p for p in root.iterdir() if not p.name.startswith("."))
    except OSError:
        return
    for project in projects:
        if not is_project_folder(project):
            continue
        try:
            children = sorted(project.iterdir())
        except OSError:
            continue
        for child in children:
            if task_item_of(child) is not None:
                yield child


__all__ = ["ARTIFACTS", "BOARDS", "KINDS", "NO_PROJECT", "PASTES", "PROJECT_MARKER", "ROOT_MARKER", "TASK_MARKER", "ensure_project", "ensure_task",
           "find_project", "find_task", "is_project_folder", "is_real_dir", "is_project_key", "kind_dir", "project_folder_name", "read_marker", "slugify",
           "task_folder_name", "task_folders", "task_item_of"]

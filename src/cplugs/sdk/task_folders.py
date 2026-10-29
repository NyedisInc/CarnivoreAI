
from __future__ import annotations

import errno
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

ROOT_MARKER = ".boards-root"
PROJECT_MARKER = ".tm-project"
TASK_MARKER = ".tm-task"
STORE_KEY = "store"
NO_PROJECT = "no-project"
ROOT_PORT = "reviewboard.root"
PASTES = "pastes"
ARTIFACTS = "artifacts"
BOARDS = "boards"
KINDS = (PASTES, ARTIFACTS, BOARDS)
GIT_IGNORED_KINDS = frozenset({PASTES, ARTIFACTS})
GITIGNORE = ".gitignore"
GITIGNORE_BODY = b"*\n"
PRIVATE_KINDS = frozenset({PASTES, ARTIFACTS})
FILE_ID_PATTERN = re.compile(r"^[0-9a-f]{8}$")
Before = Callable[[str, Path, Optional[Dict[str, Any]]], None]
STORE_SUFFIX = 8
UNSTAMPED_SUFFIX = "0" * STORE_SUFFIX
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


def task_folder_name(item_id: int, title: Optional[str], suffix: Optional[str] = None) -> str:
    plain = f"{slugify(title, TASK_FALLBACK)}-{int(item_id)}"
    return f"{plain}-{suffix}" if suffix else plain


def within(root_real: Path, folder: Path) -> bool:
    try:
        return root_real in folder.resolve(strict=True).parents
    except OSError:
        return False


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


def is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def task_file_problem(path: Path, roots: Sequence[Path], file_id: str, item_id: Optional[int] = None,
                      kinds: frozenset = PRIVATE_KINDS) -> Optional[str]:
    kind_dir, task = path.parent, path.parent.parent
    if not FILE_ID_PATTERN.match(file_id or "") or not path.name.startswith(f"{file_id}-"):
        return "its name is not a stored file's"
    if kind_dir.name not in kinds:
        return "it is not in a pastes or artifacts folder"
    if not roots:
        return "no Task Manager folder is set"
    if not is_regular_file(path):
        return "it is not a regular file (or is a link)"
    if not (is_real_dir(kind_dir) and is_real_dir(task)):
        return "its folder is a link"
    if not any(within(Path(root).resolve(), path) for root in roots):
        return "it lies outside the Task Manager folder"
    marked = task_item_of(task)
    if marked is None:
        return "its folder is not a task folder"
    if item_id is not None and marked != item_id:
        return "its folder belongs to another task"
    return None


def find_project(root: Path, list_key: str) -> Optional[Path]:
    if not is_project_key(list_key):
        folder = root / NO_PROJECT
        return folder if is_project_folder(folder) else None
    for folder in sorted(root.glob(f"*-{int(list_key)}")):
        if is_project_folder(folder) and project_list_of(folder) == str(int(list_key)):
            return folder
    return None


def tasks_for(root: Path, item_id: int) -> List[Path]:
    item = int(item_id)
    return [f for f in sorted([*root.glob(f"*/*-{item}"), *root.glob(f"*/*-{item}-{'?' * STORE_SUFFIX}")])
            if is_project_folder(f.parent) and task_item_of(f) == item]


def find_task(root: Path, item_id: int, store_id: Optional[str] = None) -> Optional[Path]:
    found = tasks_for(root, item_id)
    own = next((f for f in found if store_id and task_store_of(f) == store_id), None)
    return own if own is not None else next((f for f in found if task_store_of(f) is None), None)


def new_task_dir(parent: Path, item_id: int, title: Optional[str], store_id: Optional[str] = None) -> Path:
    plain = parent / task_folder_name(item_id, title)
    if task_item_of(plain) != int(item_id):
        return plain
    return parent / task_folder_name(item_id, title, store_id[:STORE_SUFFIX] if store_id else UNSTAMPED_SUFFIX)


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


def task_store_of(folder: Path) -> Optional[str]:
    marker = read_marker(folder, TASK_MARKER)
    value = marker.get(STORE_KEY) if marker else None
    return value if isinstance(value, str) and value else None


def ensure_task(root: Path, item_id: int, list_key: str, project_name: Optional[str], title: Optional[str],
                before: Optional[Before] = None, store_id: Optional[str] = None) -> Path:
    found = find_task(root, item_id, store_id)
    if found is not None:
        return found
    parent = ensure_project(root, list_key, project_name, before)
    folder = new_task_dir(parent, item_id, title, store_id)
    if task_item_of(folder) == int(item_id):
        raise FileExistsError(errno.EEXIST, "the second task folder name is taken", str(folder))
    _announce(before, "dir", folder, None)
    _announce(before, "marker", folder / TASK_MARKER, {"item_id": int(item_id), "list": list_key})
    _make_dir(folder)
    _write_marker(folder, TASK_MARKER, {"item_id": int(item_id), "list": list_key, "title": title, "created_at": _now(),
                                        **({STORE_KEY: store_id} if store_id else {})})
    return folder


def kind_dir(task: Path, kind: str, create: bool = True, before: Optional[Before] = None) -> Path:
    if kind not in KINDS:
        raise ValueError(f"unknown task folder kind {kind!r}")
    folder = task / kind
    if create:
        _announce(before, "dir", folder, None)
        _make_dir(folder, 0o700 if kind in PRIVATE_KINDS else 0o755)
        if kind in GIT_IGNORED_KINDS:
            _write_once(folder / GITIGNORE, GITIGNORE_BODY)
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


__all__ = ["ARTIFACTS", "BOARDS", "GITIGNORE", "GITIGNORE_BODY", "KINDS", "NO_PROJECT", "PASTES", "PROJECT_MARKER", "ROOT_MARKER", "STORE_KEY", "TASK_MARKER", "UNSTAMPED_SUFFIX", "ensure_project", "ensure_task",
           "find_project", "find_task", "new_task_dir", "within", "is_project_folder", "is_real_dir", "is_project_key", "kind_dir", "project_folder_name", "read_marker", "slugify",
           "task_folder_name", "task_folders", "tasks_for", "task_item_of", "task_store_of"]

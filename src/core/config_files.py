from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Iterator, Optional

import structlog

from src.core import app_config_guard
from src.core.slash_command_discovery import CLAUDE_HOME
from src.core.config_files_constants import (
    ALLOWED_TOP_LEVEL_FILES,
    ALLOWED_TOP_LEVEL_DIRS,
    READONLY_COLLAPSED_DIRS,
    BLOCKLIST_ONLY_ROOTS,
    HIDE_NAMES,
    HIDE_PREFIXES,
    MAX_DIR_ENTRIES,
    MAX_READ_BYTES,
    MAX_TREE_NODES,
    MORE_MARKER_KIND,
    TREE_MAX_DEPTH,
)
from src.core.config_files_io import atomic_write, atomic_write_bytes, classify, is_sensitive_name

logger = structlog.get_logger()


class ConfigFileError(ValueError):
    pass


class ConfigFileUnreadableError(ConfigFileError):
    pass


class NotAFileError(ConfigFileError):
    pass


class FileTooLargeError(ConfigFileError):
    pass


class FileNotTextError(ConfigFileError):
    pass


class FileChangedOnDiskError(ConfigFileError):

    CODE = "file_changed_on_disk"

    def __init__(self, current_sha256: Optional[str]) -> None:
        super().__init__("the file changed on disk since it was read")
        self.current_sha256 = current_sha256

    def as_detail(self) -> dict:
        return {"code": self.CODE, "detail": str(self), "sha256": self.current_sha256}


_write_locks: dict[str, threading.Lock] = {}
_write_locks_guard = threading.Lock()


@contextmanager
def _path_write_lock(path: Path) -> Iterator[None]:
    key = str(path)
    with _write_locks_guard:
        lock = _write_locks.setdefault(key, threading.Lock())
    with lock:
        yield


def file_revision(path: Path) -> tuple[Optional[str], Optional[int]]:
    if not path.is_file():
        return None, None
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_mtime_ns


@dataclass
class TreeNode:
    name: str
    rel_path: str
    is_dir: bool
    is_executable: bool = False
    is_sensitive: bool = False
    read_only: bool = False
    collapsed: bool = False
    children: list = field(default_factory=list)
    children_loaded: bool = True
    list_error: Optional[str] = None
    more_not_shown: int = 0


def _is_hidden(name: str, root_id: str) -> bool:
    if root_id in BLOCKLIST_ONLY_ROOTS:
        return False
    if name in HIDE_NAMES:
        return True
    return any(name.startswith(p) for p in HIDE_PREFIXES)


def resolve_roots(project_path: Optional[str]) -> dict:
    roots = {"user": CLAUDE_HOME.resolve()}
    if project_path:
        workdir_candidate = Path(project_path)
        if workdir_candidate.is_dir():
            roots["workdir"] = workdir_candidate.resolve()
    return roots


def resolve_safe_path(root_id: str, rel_path: str, project_path: Optional[str]) -> Path:
    roots = resolve_roots(project_path)
    root = roots.get(root_id)
    if root is None:
        raise ConfigFileError(f"unknown or unavailable root: {root_id}")

    raw = (rel_path or "").strip()
    if raw.startswith("/") or Path(raw).is_absolute() or PureWindowsPath(raw).is_absolute():
        raise ConfigFileError("absolute paths are not allowed")

    rel_path = raw.strip("/")
    if rel_path in ("", "."):
        return root

    parts = rel_path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ConfigFileError("invalid path")

    if root_id not in BLOCKLIST_ONLY_ROOTS:
        top = parts[0]
        if top not in ALLOWED_TOP_LEVEL_FILES and top not in ALLOWED_TOP_LEVEL_DIRS and top not in READONLY_COLLAPSED_DIRS:
            raise ConfigFileError(f"'{top}' is not an allowed claude-config entry")

    for p in parts:
        if _is_hidden(p, root_id):
            raise ConfigFileError("path refers to a hidden/state entry, not a browsable file")

    candidate = (root / Path(*parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ConfigFileError("path escapes the allowed root")

    return candidate


def _sorted_entries(directory: Path) -> list:
    return sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))


def _node_to_dict(n: TreeNode) -> dict:
    return {
        "name": n.name,
        "rel_path": n.rel_path,
        "is_dir": n.is_dir,
        "is_executable": n.is_executable,
        "is_sensitive": n.is_sensitive,
        "read_only": n.read_only,
        "collapsed": n.collapsed,
        "children": [_node_to_dict(c) for c in n.children]
        + ([_more_marker(n.more_not_shown)] if n.more_not_shown else []),
        "children_loaded": n.children_loaded,
        "list_error": n.list_error,
    }


def _more_marker(count: int) -> dict:
    return {"kind": MORE_MARKER_KIND, "name": "", "rel_path": "", "is_dir": False,
            "more_not_shown": count}


@dataclass
class _NodeBudget:

    remaining: int


def _build_node(root: Path, path: Path, depth: int, max_depth: int, root_id: str,
                budget: Optional[_NodeBudget] = None) -> Optional[TreeNode]:
    name = path.name
    if _is_hidden(name, root_id):
        return None
    if depth == 0 and root_id not in BLOCKLIST_ONLY_ROOTS:
        if path.is_dir() and name not in ALLOWED_TOP_LEVEL_DIRS and name not in READONLY_COLLAPSED_DIRS:
            return None
        if path.is_file() and name not in ALLOWED_TOP_LEVEL_FILES:
            return None

    is_executable, is_sensitive, read_only = classify(root, path)
    rel = str(path.relative_to(root)).replace(os.sep, "/")
    collapsed = read_only
    is_dir = path.is_dir()
    descend = is_dir and depth < max_depth and not path.is_symlink()
    node = TreeNode(
        name=name,
        rel_path=rel,
        is_dir=is_dir,
        is_executable=is_executable,
        is_sensitive=is_sensitive,
        read_only=read_only,
        collapsed=collapsed,
        children_loaded=(not is_dir) or descend,
    )

    if descend:
        try:
            entries = _sorted_entries(path)
        except OSError as exc:
            logger.warning("config_files_listdir_failed", path=str(path), error=str(exc))
            node.list_error = exc.strerror or str(exc)
            entries = []
        shown = entries[:MAX_DIR_ENTRIES]
        built = 0
        for child in shown:
            if budget is not None and budget.remaining <= 0:
                break
            if budget is not None:
                budget.remaining -= 1
            built += 1
            child_node = _build_node(root, child, depth + 1, max_depth, root_id, budget)
            if child_node is not None:
                node.children.append(child_node)
        node.more_not_shown = max(0, len(entries) - built)

    return node


def list_subtree(
    root_id: str,
    rel_path: str,
    project_path: Optional[str],
    levels: int = TREE_MAX_DEPTH + 1,
) -> list:
    roots = resolve_roots(project_path)
    root = roots.get(root_id)
    if root is None:
        raise ConfigFileError(f"unknown or unavailable root: {root_id}")

    resolved = resolve_safe_path(root_id, rel_path, project_path)
    requested = (rel_path or "").strip().strip("/")
    is_root = requested in ("", ".")

    if not resolved.is_dir():
        if is_root:
            return []
        raise ConfigFileError("not a directory")

    parts = requested.split("/") if not is_root else []
    walk_base = root if is_root else root / Path(*parts)
    base_depth = len(parts)
    max_depth = base_depth + max(0, levels - 1)

    try:
        entries = _sorted_entries(walk_base)
    except OSError as exc:
        logger.warning(
            "config_files_list_root_failed",
            path=str(walk_base),
            root=root_id,
            rel_path=rel_path,
            error=str(exc),
        )
        raise ConfigFileUnreadableError(
            f"{root_id} root could not be read: {exc.strerror or exc}"
            if is_root
            else f"'{rel_path}' could not be read: {exc.strerror or exc}"
        ) from exc

    nodes = []
    budget = _NodeBudget(MAX_TREE_NODES)
    for entry in entries[:MAX_DIR_ENTRIES]:
        node = _build_node(root, entry, depth=base_depth, max_depth=max_depth, root_id=root_id,
                           budget=budget)
        if node is not None:
            nodes.append(node)
    out = [_node_to_dict(n) for n in nodes]
    if len(entries) > MAX_DIR_ENTRIES:
        out.append(_more_marker(len(entries) - MAX_DIR_ENTRIES))
    return out


def list_tree(root_id: str, project_path: Optional[str], max_depth: int = TREE_MAX_DEPTH) -> list:
    return list_subtree(root_id, "", project_path, levels=max_depth + 1)


def _pinned_file(path_text: str, trusted_root: Optional[str] = None) -> tuple[Path, Path]:
    path = Path(path_text)
    if not path.is_absolute() or '\0' in path_text:
        raise ConfigFileError("the opened file path changed or is invalid")
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        raise ConfigFileError(f"the opened file path is unavailable: {exc}") from exc
    if resolved != path:
        raise ConfigFileError("the opened file path changed or is invalid")
    try:
        user_root = CLAUDE_HOME.resolve()
    except (OSError, RuntimeError) as exc:
        raise ConfigFileError(f"the user config root is unavailable: {exc}") from exc
    if path.is_relative_to(user_root):
        try:
            path = resolve_safe_path("user", path.relative_to(user_root).as_posix(), None)
        except (OSError, RuntimeError) as exc:
            raise ConfigFileError(f"the opened file path is unavailable: {exc}") from exc
        return path, user_root
    if trusted_root:
        root = Path(trusted_root)
        try:
            root_is_stable = root.resolve() == root
        except (OSError, RuntimeError) as exc:
            raise ConfigFileError(f"the file's project root is unavailable: {exc}") from exc
        if not root.is_absolute() or not root_is_stable or not path.is_relative_to(root):
            raise ConfigFileError("the file's project root changed or is invalid")
        return path, root
    return path, Path(path.anchor)


def read_file(root_id: str, rel_path: str, project_path: Optional[str], *, _pinned_absolute: bool = False,
              _trusted_root: Optional[str] = None) -> dict:
    if _pinned_absolute:
        path, root = _pinned_file(rel_path, _trusted_root)
    else:
        roots = resolve_roots(project_path)
        root = roots[root_id] if root_id in roots else None
        path = resolve_safe_path(root_id, rel_path, project_path)
    if not path.is_file():
        raise NotAFileError("not a file")
    try:
        stat = path.stat()
        size = stat.st_size
        if size > MAX_READ_BYTES:
            raise FileTooLargeError(f"file too large to edit here ({size} bytes)")
        raw = path.read_bytes()
    except OSError as exc:
        logger.warning("config_files_read_failed", path=str(path), error=str(exc))
        raise ConfigFileUnreadableError(f"could not read the file: {exc.strerror or exc}") from exc
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise FileNotTextError("file is not text/utf-8 - not editable here")

    is_executable, is_sensitive, read_only = classify(root or path.parent, path)
    return {
        "content": content,
        "is_executable": is_executable,
        "is_sensitive": is_sensitive,
        "read_only": read_only,
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "mtime_ns": stat.st_mtime_ns,
    }


def write_file(
    root_id: str,
    rel_path: str,
    content: str,
    project_path: Optional[str],
    acknowledge_executable: bool = False,
    acknowledge_sensitive: bool = False,
    expected_sha256: Optional[str] = None,
    *, _pinned_absolute: bool = False, _trusted_root: Optional[str] = None,
) -> dict:
    if _pinned_absolute:
        path, root = _pinned_file(rel_path, _trusted_root)
    else:
        path = resolve_safe_path(root_id, rel_path, project_path)
        roots = resolve_roots(project_path)
        root = roots[root_id]
    app_config_guard.refuse_if_app_config(path, root_id=root_id, rel_path=rel_path)
    is_executable, is_sensitive, read_only = classify(root, path)
    if read_only:
        raise ConfigFileError("this file is under a read-only root (plugins/)")
    if is_executable and not acknowledge_executable:
        raise ConfigFileError(
            "this file is executed automatically by claude code - "
            "write refused without explicit confirmation"
        )
    if is_sensitive and not acknowledge_sensitive:
        raise ConfigFileError(
            "this file looks like credentials/a secret/a private key - "
            "write refused without explicit confirmation"
        )

    if path.suffix == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise ConfigFileError(f"invalid json: {exc.msg} (line {exc.lineno}, col {exc.colno})")

    with _path_write_lock(path):
        if expected_sha256 is not None:
            try:
                current_sha256, _ = file_revision(path)
            except OSError as exc:
                raise ConfigFileError(f"could not read the file to check it: {exc.strerror}")
            if current_sha256 != expected_sha256:
                raise FileChangedOnDiskError(current_sha256)
        backed_up = _backup_and_write(path, content)

    logger.info(
        "config_files_write",
        root=root_id,
        rel_path=rel_path,
        is_executable=is_executable,
        is_sensitive=is_sensitive,
        backed_up=backed_up,
        bytes=len(content),
        checked_revision=expected_sha256 is not None,
    )
    try:
        new_sha256, new_mtime_ns = file_revision(path)
    except OSError as exc:
        logger.warning("config_files_revision_after_write_failed", path=str(path), error=str(exc))
        new_sha256, new_mtime_ns = None, None
    return {
        "backed_up": backed_up,
        "is_executable": is_executable,
        "is_sensitive": is_sensitive,
        "sha256": new_sha256,
        "mtime_ns": new_mtime_ns,
    }


def _backup_and_write(path: Path, content: str) -> bool:
    backed_up = False
    mode: Optional[int] = None
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        try:
            backup_path = path.with_suffix(path.suffix + ".bak")
            atomic_write_bytes(backup_path, path.read_bytes(), mode)
            backed_up = True
        except OSError as exc:
            logger.warning("config_files_backup_failed", path=str(path), error=str(exc))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, content, mode=mode)
    return backed_up

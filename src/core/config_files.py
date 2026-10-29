from __future__ import annotations

import hashlib
import json
import os
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
    MORE_MARKER_KIND,
    TREE_MAX_DEPTH,
)
from src.core.config_files_io import atomic_write, classify, is_sensitive_name

logger = structlog.get_logger()


class ConfigFileError(ValueError):
    pass


class ConfigFileUnreadableError(ConfigFileError):
    """Raised when a ROOT exists but its own contents could not be
    enumerated (``OSError`` from ``iterdir()`` - typically a permissions
    problem, not a bad request). This is the THREE-OUTCOME RULE's third
    state for this endpoint: distinct from "listed, zero entries" (a
    genuinely empty/absent directory) and from an ordinary
    ``ConfigFileError`` (client sent something invalid). Routes layer
    maps this to HTTP 503 rather than 400, so the client can render "I
    could not check this" instead of silently treating it as "there is
    nothing here" - see config_files.py's module docstring and
    CLAUDE.md's THREE-OUTCOME RULE section for why that conflation is a
    named, recurring bug class in this project.

    A subdirectory (not the root itself) hitting the same OSError does
    NOT raise this - it would abort the whole tree over one bad
    subdirectory. That case sets ``TreeNode.list_error`` instead, so the
    rest of the tree still renders and only that one node says it
    could not be evaluated.
    """


class NotAFileError(ConfigFileError):
    """The resolved path is not a regular file (missing, or a directory)."""


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
    """One entry in the rendered file tree.

    Inputs (fields): name (str) - basename; rel_path (str) - path
      relative to the root, forward-slash separated; is_dir (bool);
      is_executable (bool) - True for a .py/.cjs/.js/.sh file under
      hooks/ or scripts/; is_sensitive (bool) - True for a
      credentials/secret/key-shaped file (see SENSITIVE_*); read_only
      (bool) - True for anything under a READONLY_COLLAPSED_DIRS root;
      collapsed (bool) - hint to the frontend to render this subtree
      closed by default; children (list[TreeNode]) - populated for
      directories; children_loaded (bool) - whether `children` is the
      COMPLETE answer for this node (see below); list_error (str|None) -
      set instead of an empty `children` when THIS directory's own
      entries could not be enumerated (OSError) - the three-outcome
      rule's "could not evaluate", kept distinct from a directory that
      was read successfully and is simply empty.
    """
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


def _build_node(root: Path, path: Path, depth: int, max_depth: int, root_id: str) -> Optional[TreeNode]:
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
    node = TreeNode(
        name=name,
        rel_path=rel,
        is_dir=is_dir,
        is_executable=is_executable,
        is_sensitive=is_sensitive,
        read_only=read_only,
        collapsed=collapsed,
        children_loaded=(not is_dir) or depth < max_depth,
    )

    if is_dir and depth < max_depth:
        try:
            entries = _sorted_entries(path)
        except OSError as exc:
            # could not
            # could not
            logger.warning("config_files_listdir_failed", path=str(path), error=str(exc))
            node.list_error = exc.strerror or str(exc)
            entries = []
        for child in entries[:MAX_DIR_ENTRIES]:
            child_node = _build_node(root, child, depth + 1, max_depth, root_id)
            if child_node is not None:
                node.children.append(child_node)
        node.more_not_shown = max(0, len(entries) - MAX_DIR_ENTRIES)

    return node


def list_subtree(
    root_id: str,
    rel_path: str,
    project_path: Optional[str],
    levels: int = TREE_MAX_DEPTH + 1,
) -> list:
    """
    Description: list the entries directly inside ONE directory of a root,
      recursing ``levels - 1`` further levels beneath them. This is the
      single tree-walking implementation; ``list_tree`` is this function
      called on the root itself. A shallow read and a full read therefore
      cannot drift in ordering, filtering, flags or shape - there is only
      one code path producing any of them.
    Inputs:
      root_id (str) - "user" or "workdir".
      rel_path (str) - directory to list, relative to the root, forward
        slash separated. "" (or ".") means the root itself.
      project_path (str|None) - required for "workdir".
      levels (int) - how many LEVELS of nodes to return. 1 returns the
        directory's own entries with no children; the default returns the
        same full depth ``list_tree`` always has.
    Output: list[dict] - the directory's entries, JSON-serializable, each
      shaped exactly as ``list_tree`` shapes a node, and each ``rel_path``
      relative to the ROOT (never to ``rel_path``) so it can be handed
      straight back to this function or to ``read_file``.
    Raises:
      ConfigFileError - unknown/unavailable root, a path that fails
        ``resolve_safe_path`` (traversal, absolute, hidden component, not
        allow-listed), or a path that is not a directory.
      ConfigFileUnreadableError - the requested directory exists but its
        own entries could not be enumerated (OSError - typically
        permissions). The three-outcome rule's third state for THIS
        request, exactly as it is for a root: NOT the same as "listed,
        zero entries", which returns an empty list normally.

    SECURITY. The requested directory goes through ``resolve_safe_path``,
    which is the same and only guard ``read_file`` and ``write_file`` use:
    absolute paths refused, ``..`` refused, hidden components refused,
    allow-list applied for non-BLOCKLIST_ONLY_ROOTS, and containment
    checked COMPONENT-WISE with ``Path.relative_to`` after ``resolve()``
    rather than with a string prefix test - so a sibling directory whose
    name merely starts with the root's name ("/Users/example" against
    "/Users/example") is not inside it, and a symlink bridge out of the
    root resolves to where it really points and is refused there. Because
    ``resolve()`` runs on every expansion, listing a directory one level at
    a time is STRICTER than the full-tree walk, not weaker: the recursive
    walk descends through a symlink without re-resolving, while every
    shallow expansion re-checks containment from the root.

    The depth-0 allow-list gate inside ``_build_node`` is keyed on the
    node's TRUE depth below the root, which this function computes from
    the resolved path rather than restarting the count at zero. Restarting
    it would apply a top-level allow-list to entries that are not
    top-level, and, worse, would let a caller reach a non-allow-listed
    top-level name one segment at a time.
    Example: list_subtree("user", "hooks", None, levels=1)
      -> [{"name": "op-readonly-guard.py", "rel_path": "hooks/op-...", ...}]
    """
    roots = resolve_roots(project_path)
    root = roots.get(root_id)
    if root is None:
        raise ConfigFileError(f"unknown or unavailable root: {root_id}")

    resolved = resolve_safe_path(root_id, rel_path, project_path)
    requested = (rel_path or "").strip().strip("/")
    is_root = requested in ("", ".")

    if not resolved.is_dir():
        if is_root:
            # not a directory
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
    for entry in entries[:MAX_DIR_ENTRIES]:
        node = _build_node(root, entry, depth=base_depth, max_depth=max_depth, root_id=root_id)
        if node is not None:
            nodes.append(node)
    out = [_node_to_dict(n) for n in nodes]
    if len(entries) > MAX_DIR_ENTRIES:
        out.append(_more_marker(len(entries) - MAX_DIR_ENTRIES))
    return out


def list_tree(root_id: str, project_path: Optional[str], max_depth: int = TREE_MAX_DEPTH) -> list:
    """
    Description: build the full hide-list-filtered file tree for one
      root ("user" is additionally allow-listed; "workdir" is
      not). A thin alias for ``list_subtree`` on the root itself, kept
      because it is the name every existing caller and test uses and
      because "the whole tree for this root" is worth saying directly.
    Inputs:
      root_id (str) - "user" or "workdir".
      project_path (str|None) - required for "workdir".
      max_depth (int) - recursion cap as a DEPTH (a root's direct children
        are depth 0), so it permits ``max_depth + 1`` levels of nodes.
        Defaults to TREE_MAX_DEPTH.
    Output: list[dict] - top-level TreeNode entries, JSON-serializable
      (dataclasses.asdict shape). For allow-listed roots the order is
      ALLOWED_TOP_LEVEL_FILES then ALLOWED_TOP_LEVEL_DIRS then
      READONLY_COLLAPSED_DIRS, each sorted alphabetically within its
      group; "workdir" is files-then-dirs, alphabetical.
    Raises:
      ConfigFileError - unknown/unavailable root (client-caused; the
        working directory/root simply doesn't apply here).
      ConfigFileUnreadableError - the root exists but its own entries
        could not be enumerated (OSError - typically permissions). This
        is the three-outcome rule's third state: NOT the same as "root
        exists, zero entries", which returns an empty list normally.
    """
    return list_subtree(root_id, "", project_path, levels=max_depth + 1)


def read_file(root_id: str, rel_path: str, project_path: Optional[str]) -> dict:
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
) -> dict:
    """
    Description: write one browsable file, always backing up the
      previous bytes first (atomic tmp-file + fsync + os.replace, same
      convention as ``Settings.update_settings_config()``).
      ``.json``-suffixed files are parsed with ``json.loads`` before
      anything touches disk - a parse failure raises and nothing is
      written (and the exception message never includes file content,
      only json.JSONDecodeError's own line/col/msg). A write to an
      executable file (see EXECUTABLE_DIRS / EXECUTABLE_EXTENSIONS)
      additionally REQUIRES ``acknowledge_executable=True``, and a write
      to a sensitive file (see SENSITIVE_*) additionally REQUIRES
      ``acknowledge_sensitive=True`` - the routes layer only sets either
      flag after the client's confirm modal returned true; this is the
      server-side half of that confirmation, not just a UI nicety.
    Inputs:
      root_id (str); rel_path (str); project_path (str|None) - see
        resolve_safe_path().
      content (str) - new file contents.
      acknowledge_executable (bool) - must be True to write an
        executable file; ignored (no effect) for non-executable files.
      acknowledge_sensitive (bool) - must be True to write a sensitive
        (credentials/secret/key-shaped) file; ignored for others.
      expected_sha256 (str|None) - the ``sha256`` the caller's read
        answered. When given, the write is REFUSED unless the file on disk
        still hashes to it (a file gone since counts as changed); None
        keeps the old last-save-wins behavior for callers that never read.
    Output: dict - {"backed_up": bool, "is_executable": bool,
      "is_sensitive": bool, "sha256": str | None, "mtime_ns": int | None} -
      the last two are the NEW revision, the base for the next save (None
      when the save landed but the file could not be re-read after it).
    Raises: ConfigFileError - invalid/read-only path, malformed JSON for
      a .json file, an executable write without acknowledgement, or a
      sensitive write without acknowledgement. FileChangedOnDiskError -
      ``expected_sha256`` no longer matches the file on disk.
    """
    path = resolve_safe_path(root_id, rel_path, project_path)
    app_config_guard.refuse_if_app_config(path, root_id=root_id, rel_path=rel_path)
    roots = resolve_roots(project_path)
    root = roots[root_id]

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
    if path.exists():
        try:
            backup_path = path.with_suffix(path.suffix + ".bak")
            backup_path.write_bytes(path.read_bytes())
            backed_up = True
        except OSError as exc:
            logger.warning("config_files_backup_failed", path=str(path), error=str(exc))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, content)
    return backed_up

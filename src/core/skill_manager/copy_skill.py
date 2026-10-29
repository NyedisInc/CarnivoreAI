
from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import structlog

from src.core.live_install_roots import SCOPE_GLOBAL, TRASH_DIR_NAME
from src.core.resource_push import notifier
from src.core.resource_push.topics import LOCAL_SKILLS
from src.core.skill_manager.command_center import SIDECAR_NAME
from src.core.sessions.ports import Target
from src.core.skill_manager.root_create import RootCreateRefused, create_leaf_root, creation_boundary
from src.core.skill_manager.types import CLAUDE, CODEX, SCOPE_PERSONAL, SCOPE_PROJECT
from src.core.skills.roots import (
    ROOT_ABSENT, ROOT_IS_SYMLINK, ROOT_PARENT_IS_SYMLINK, TARGET_EXISTS, TARGET_IS_SYMLINK, check_root, unsafe_name_reason,
)
from src.core.skills.targets import SymlinkInTree, TrashFolderIsLink, copy_tree, remove_tree, swap_in
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()

MAX_COPY_BYTES = 10 * 1024 * 1024
MAX_COPY_FILES = 500
STAGING_PREFIX = ".carnivore-staging-"
CODEX_KEYS = frozenset({"name", "description"})


class CopyError(Exception):

    def __init__(self, status: int, code: str, detail: str, trashed_to: Optional[str] = None) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail, self.trashed_to = status, code, detail, trashed_to


def inspect_source(path: Path) -> Dict[str, Any]:
    files: List[str] = []
    total = 0
    for current, dirs, names in os.walk(path, followlinks=False):
        dirs.sort()
        for name in sorted(dirs) + sorted(names):
            full = os.path.join(current, name)
            mode = os.lstat(full).st_mode
            if stat.S_ISLNK(mode):
                raise CopyError(409, "symlink_in_skill", f"{os.path.relpath(full, path)} is a symlink; a copy never follows one")
            if stat.S_ISREG(mode) and not (current == str(path) and name == SIDECAR_NAME):
                files.append(os.path.relpath(full, path))
                total += os.lstat(full).st_size
            elif not stat.S_ISREG(mode) and not stat.S_ISDIR(mode):
                raise CopyError(409, "unreadable", f"{os.path.relpath(full, path)} is not a regular file or folder")
        if len(files) > MAX_COPY_FILES or total > MAX_COPY_BYTES:
            raise CopyError(409, "too_large", f"over {MAX_COPY_FILES} files or {MAX_COPY_BYTES // (1024 * 1024)} MiB")
    files.sort()
    digest = tree_digest(path, files)
    posix = [Path(f).as_posix() for f in files]
    return {
        "digest": digest, "files": len(files), "bytes": total,
        "scripts": [f for f in posix if f.startswith("scripts/")],
        "exec_files": [f for f in posix if os.lstat(path / f).st_mode & 0o111],
    }


def tree_digest(path: Path, files: Sequence[str]) -> str:
    hasher = hashlib.sha256()
    for rel in files:
        hasher.update(Path(rel).as_posix().encode("utf-8") + b"\0")
        try:
            fd = os.open(path / rel, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as handle:
                hasher.update(b"x" if os.fstat(handle.fileno()).st_mode & 0o111 else b"-")
                for block in iter(lambda: handle.read(1 << 20), b""):
                    hasher.update(block)
        except OSError as exc:
            raise CopyError(409, "unreadable", f"{rel}: {exc.strerror or exc}") from None
        hasher.update(b"\0")
    return hasher.hexdigest()


def _frontmatter_keys(skill_dir: Path) -> List[str]:
    try:
        with open(skill_dir / "SKILL.md", "rb") as handle:
            text = handle.read(65536).decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    keys: List[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line[:1] not in " \t#-" and ":" in line:
            keys.append(line.split(":", 1)[0].strip())
    return keys


def _git_tracked(col: Dict[str, Any]) -> bool:
    return col["scope"] == SCOPE_PROJECT and (Path(col["leaf"]).parent.parent / ".git").exists()


def _refuse(col: Dict[str, Any], code: str, detail: str, status: str = "refused", **extra: Any) -> Dict[str, Any]:
    return {"column_id": col["column_id"], "label": col["label"], "status": status, "code": code, "detail": detail, **extra}


def _write(col: Dict[str, Any], src: Path, folder: str, info: Dict[str, Any], replace_existing: bool,
           stamp: str, boundary: Optional[Path]) -> Dict[str, Any]:
    root = Path(col["leaf"])
    if not root.is_dir():
        if boundary is None:
            raise CopyError(409, "root_absent", "the skills folder is missing and may not be created here")
        try:
            create_leaf_root(root, boundary)
        except RootCreateRefused as exc:
            raise CopyError(409, exc.code, exc.detail) from None
    assert_test_write_allowed(root / STAGING_PREFIX)
    staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=root))
    try:
        staged, dest = staging / folder, root / folder
        copy_tree(src, staged, exec_paths=frozenset(info["exec_files"]), skip_names=frozenset({SIDECAR_NAME}))
        if tree_digest(staged, sorted(Path(f).as_posix() for f in _regular_files(staged))) != info["digest"]:
            raise CopyError(409, "source_changed", "the skill changed while it was being copied")
        if replace_existing:
            trash = root.parent / TRASH_DIR_NAME
            try:
                displaced = swap_in(staged, dest, trash_root=trash, stamp=stamp)
            except OSError as exc:
                aside = trash / f"{folder}-{stamp}"
                if os.path.lexists(aside) and not os.path.lexists(dest):
                    assert_test_write_allowed(aside)
                    assert_test_write_allowed(dest)
                    try:
                        os.replace(aside, dest)
                    except OSError:
                        raise CopyError(409, "swap_failed", "the old copy is in the trash and the new one did not land",
                                        trashed_to=str(aside)) from None
                raise exc
            return {"status": "replaced", "trashed_to": str(displaced)}
        if os.path.lexists(dest):
            raise CopyError(409, "exists", "a folder of that name appeared meanwhile")
        assert_test_write_allowed(staged)
        assert_test_write_allowed(dest)
        os.replace(staged, dest)
        return {"status": "copied"}
    finally:
        remove_tree(staging)


def _regular_files(path: Path) -> List[str]:
    return sorted(
        os.path.relpath(os.path.join(cur, n), path)
        for cur, _dirs, names in os.walk(path, followlinks=False) for n in names
    )


def copy_skill(
    matrix: Dict[str, Any], *, source_location_id: str, source_column_id: str, targets: Sequence[Dict[str, Any]],
    dry_run: bool, generation: Optional[str], source_digest: Optional[str], home: Path, stamp: str,
) -> Dict[str, Any]:
    if not dry_run and not (generation and source_digest):
        raise CopyError(400, "stale_check_required", "generation and source_digest are required for a real copy")
    columns = {c["column_id"]: c for c in matrix["columns"]}
    src_col = columns.get(source_column_id)
    hit = next(((r, c) for r in matrix["rows"] for c in r["cells"].get(source_column_id, []) if c["location_id"] == source_location_id), None)
    if src_col is None or hit is None or src_col["scope"] not in (SCOPE_PERSONAL, SCOPE_PROJECT):
        raise CopyError(404, "unknown_source", "unknown or stale source")
    row, cell = hit
    folder = cell["folder"]
    if unsafe_name_reason(folder) is not None:
        raise CopyError(409, "target_unsafe", "the folder name is not safe to copy")
    src_root = Path(src_col["path"])
    src = src_root / folder
    if src.is_symlink() or not src.is_dir():
        raise CopyError(409, "target_unsafe", "the source is not a plain folder inside its skills root")
    info = inspect_source(src)
    if not dry_run and (generation != matrix["generation"] or source_digest != info["digest"]):
        raise CopyError(409, "stale", "the skills changed since you looked; reload and review again")
    keys = _frontmatter_keys(src)
    personal = next((c for c in matrix["columns"] if c["harness"] == CLAUDE and c["scope"] == SCOPE_PERSONAL and c["writable"]), None)
    personal_has = bool(personal and row["cells"].get(personal["column_id"], [{}])[0].get("folder"))
    ctx = {"cell": cell, "folder": folder, "info": info, "src": src, "keys": keys, "personal_has": personal_has,
           "dry_run": dry_run, "home": home, "stamp": stamp, "harness": src_col["harness"]}
    results: List[Dict[str, Any]] = []
    seen: set = set()
    try:
        for target in targets:
            col = columns.get(target.get("column_id"))
            if col is None:
                raise CopyError(404, "unknown_target", "unknown or stale target column")
            if col["column_id"] in seen:
                continue
            seen.add(col["column_id"])
            results.append(_target_result(col, target, matrix["rows"], ctx))
    finally:
        if any(r["status"] in ("copied", "replaced") or r.get("trashed_to") for r in results):
            notifier.notify(LOCAL_SKILLS)
    return {
        "dry_run": dry_run, "generation": matrix["generation"],
        "source": {"name": row["name"], "folder": folder, "harness": src_col["harness"], "label": src_col["label"], "scope": src_col["scope"], "source_digest": info["digest"],
                   "files": info["files"], "bytes": info["bytes"], "scripts": info["scripts"], "exec_files": info["exec_files"]},
        "results": results,
    }


def _target_result(col: Dict[str, Any], target: Dict[str, Any], rows: List[Dict[str, Any]], ctx: Dict[str, Any]) -> Dict[str, Any]:
    cell, folder, info = ctx["cell"], ctx["folder"], ctx["info"]
    if cell["managed"] == "ledger":
        return _refuse(col, "use_catalog_install", "this skill came from the catalog; install it from the catalog instead",
                       "use_catalog_install", item_id=cell.get("managed_item_id"))
    if not col["writable"]:
        return _refuse(col, col["readonly_reason"] or "read_only", "that column is read only")
    root = Path(col["leaf"])
    dest = root / folder
    if os.path.realpath(dest) == os.path.realpath(ctx["src"]):
        return _refuse(col, "same_location", "that is where the skill already is", "skipped")
    state = check_root(Target(col["harness"], root), folder).state
    if state in (ROOT_PARENT_IS_SYMLINK, ROOT_IS_SYMLINK, TARGET_IS_SYMLINK):
        return _refuse(col, "target_unsafe", f"the skills folder or the folder in it is a symlink ({state})")
    exists = state == TARGET_EXISTS
    if exists and not target.get("replace"):
        return _refuse(col, "exists", "a folder of that name is already there", "skipped")
    if exists:
        if not dest.is_dir():
            return _refuse(col, "target_unsafe", "the existing entry is not a folder")
        occupant = next((c for r in rows for c in r["cells"].get(col["column_id"], []) if c["folder"] == folder), None)
        if occupant is None:
            return _refuse(col, "not_a_skill_folder", "the existing folder holds no SKILL.md, so it is not replaced")
        if occupant["managed"] == "ledger":
            return _refuse(col, "use_catalog_uninstall", "that copy is catalog-managed; uninstall it from the catalog first", "use_catalog_uninstall")
    boundary = None
    if state == ROOT_ABSENT:
        scope, project = (SCOPE_PROJECT, str(root.parent.parent)) if col["scope"] == SCOPE_PROJECT else (SCOPE_GLOBAL, None)
        boundary = creation_boundary(Target(col["harness"], root), scope, project)
        if boundary is None or (scope == SCOPE_PROJECT and os.path.realpath(boundary) == os.path.realpath(ctx["home"])):
            return _refuse(col, "root_absent", "the skills folder is missing and may not be created here")
    base = {"column_id": col["column_id"], "label": col["label"]}
    if ctx["dry_run"]:
        cross = ctx["harness"] != col["harness"]
        tracked = _git_tracked(col)
        return {
            **base, "status": "would_replace" if exists else "would_copy", "creates_root": state == ROOT_ABSENT,
            "git_tracked": tracked, "trash_new": tracked and not os.path.lexists(root.parent / TRASH_DIR_NAME),
            "accounts_sharing": col["accounts_sharing"], "cross_harness": cross,
            "ignored_frontmatter": [k for k in ctx["keys"] if k not in CODEX_KEYS] if cross and col["harness"] == CODEX else [],
            "shadowed_by_personal": ctx["personal_has"] and col["harness"] == CLAUDE and col["scope"] == SCOPE_PROJECT,
        }
    try:
        return {**base, **_write(col, ctx["src"], folder, info, exists, ctx["stamp"], boundary)}
    except CopyError as exc:
        return _refuse(col, exc.code, exc.detail, **({"trashed_to": exc.trashed_to} if exc.trashed_to else {}))
    except SymlinkInTree:
        return _refuse(col, "symlink_in_skill", "a symlink appeared in the skill while it was being copied")
    except TrashFolderIsLink:
        return _refuse(col, "target_unsafe", "the trash folder is a symlink, so nothing was moved")
    except OSError as exc:
        logger.warning("skill_copy_failed", column_id=col["column_id"], error=type(exc).__name__)
        return _refuse(col, "write_failed", f"the copy could not be written: {exc.strerror or type(exc).__name__}")

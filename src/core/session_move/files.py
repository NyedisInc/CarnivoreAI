
from __future__ import annotations

import errno
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Sequence, Tuple

import structlog

logger = structlog.get_logger()

LEFT_BEHIND_NAMES: Tuple[str, ...] = (".cc.theme",)

GIT_DIR = ".git"

BACKUP_DIRNAME = "session-moves"

MAX_CARRY_BYTES = 2 * 1024 ** 3

MAX_CARRY_FILES = 20_000


class SessionMoveFilesError(Exception):

    def __init__(self, message: str, undo_errors: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.undo_errors = list(undo_errors)


@dataclass(frozen=True)
class Inventory:

    files: Dict[str, int] = field(default_factory=dict)
    dirs: Tuple[str, ...] = ()
    left_behind: Tuple[str, ...] = ()

    @property
    def total_bytes(self) -> int:
        return sum(self.files.values())


def inventory(source: Path) -> Inventory:
    files: Dict[str, int] = {}
    dirs: List[str] = []
    left: List[str] = []

    def _raise(exc: OSError) -> None:
        raise exc

    for top, dirnames, filenames in _walk(source, _raise):
        rel_top = os.path.relpath(top, source)
        for name in list(dirnames):
            full = os.path.join(top, name)
            rel = os.path.normpath(os.path.join(rel_top, name))
            if os.path.islink(full):
                dirnames.remove(name)
                files[rel] = os.lstat(full).st_size
            else:
                dirs.append(rel)
        for name in filenames:
            rel = os.path.normpath(os.path.join(rel_top, name))
            if rel_top == "." and name in LEFT_BEHIND_NAMES:
                left.append(name)
                continue
            files[rel] = os.lstat(os.path.join(top, name)).st_size
    return Inventory(files=files, dirs=tuple(dirs), left_behind=tuple(left))


def _walk(source: Path, onerror: Callable[[OSError], None]) -> Iterator[Tuple[str, List[str], List[str]]]:
    return os.walk(str(source), topdown=True, onerror=onerror, followlinks=False)


def collisions(inv: Inventory, destination: Path) -> List[str]:
    hits: List[str] = []
    for rel in inv.files:
        if os.path.lexists(destination / rel):
            hits.append(rel)
    for rel in inv.dirs:
        target = destination / rel
        if os.path.lexists(target) and (os.path.islink(target) or not target.is_dir()):
            hits.append(rel)
    return sorted(set(hits))


def both_git(source: Path, destination: Path) -> bool:
    return os.path.lexists(source / GIT_DIR) and os.path.lexists(destination / GIT_DIR)


def backup(source: Path, inv: Inventory, backup_dir: Path, manifest: Dict[str, object]) -> Path:
    copy = backup_dir / "files"
    try:
        backup_dir.mkdir(parents=True, exist_ok=False)
        shutil.copytree(source, copy, symlinks=True)
        (backup_dir / "manifest.json").write_text(
            json.dumps({**manifest, "files": sorted(inv.files)}, indent=2), encoding="utf-8")
    except (OSError, shutil.Error) as exc:
        raise SessionMoveFilesError(f"the backup of {source} could not be made: {exc}") from exc
    missing = [rel for rel, size in inv.files.items()
               if not os.path.lexists(copy / rel) or os.lstat(copy / rel).st_size != size]
    if missing:
        raise SessionMoveFilesError(f"the backup is missing {len(missing)} file(s), first {missing[0]}; nothing was moved")
    logger.info("session_move_backup_made", source=str(source), backup=str(backup_dir), files=len(inv.files))
    return backup_dir


def _move_one(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, "already exists", str(dst))
    try:
        os.rename(src, dst)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.copy2(src, dst, follow_symlinks=False)
        if os.lstat(dst).st_size != os.lstat(src).st_size:
            os.unlink(dst)
            raise OSError(errno.EIO, "the copy came out a different size", str(dst))
        os.unlink(src)


def undo_moves(source: Path, destination: Path, moved: Sequence[str]) -> List[str]:
    errors: List[str] = []
    for rel in reversed(list(moved)):
        try:
            _move_one(destination / rel, source / rel)
        except OSError as exc:
            errors.append(f"{rel}: {exc}")
            logger.error("session_move_undo_failed", file=rel, error=str(exc))
    return errors


def move_files(source: Path, destination: Path, inv: Inventory) -> List[str]:
    moved: List[str] = []
    try:
        for rel in sorted(inv.dirs):
            (destination / rel).mkdir(parents=True, exist_ok=True)
        for rel in sorted(inv.files):
            _move_one(source / rel, destination / rel)
            moved.append(rel)
    except OSError as exc:
        undo_errors = undo_moves(source, destination, moved)
        raise SessionMoveFilesError(f"moving the files failed ({exc}); {len(moved) - len(undo_errors)} put back",
                                    undo_errors) from exc
    for rel in sorted(inv.dirs, key=lambda d: d.count(os.sep), reverse=True):
        try:
            os.rmdir(source / rel)
        except OSError:
            continue
    return moved


def verify_moved(source: Path, destination: Path, inv: Inventory) -> List[str]:
    bad: List[str] = []
    for rel, size in inv.files.items():
        there = destination / rel
        if not os.path.lexists(there) or os.lstat(there).st_size != size or os.path.lexists(source / rel):
            bad.append(rel)
    return bad

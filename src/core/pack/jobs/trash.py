
from __future__ import annotations

import errno
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote

import structlog

from src.core.test_write_guard import assert_test_write_allowed, running_under_test

log = structlog.get_logger(__name__)

MAC_TRASH_TOOL = "/usr/bin/trash"
TOOL_TIMEOUT_S = 60.0
NO_TRASH = "no_trash"
OTHER_VOLUME = "other_volume"


class TrashRefused(Exception):

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


@dataclass(frozen=True)
class TrashResult:

    where: str
    kind: Literal["platform", "carnivore"]


def _stamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%S")


def _free_name(parent: Path, name: str, stamp: str) -> Path:
    candidate = parent / f"{name}-{stamp}"
    n = 1
    while os.path.lexists(candidate):
        n += 1
        candidate = parent / f"{name}-{stamp}-{n}"
    return candidate


def _rename(source: Path, destination: Path) -> None:
    assert_test_write_allowed(destination)
    if os.path.lexists(destination):
        raise FileExistsError(str(destination))
    os.rename(source, destination)


def _with_tool(source: Path, tool: str, home: Path) -> Optional[TrashResult]:
    if not (os.path.isfile(tool) and os.access(tool, os.X_OK)):
        return None
    if tool == MAC_TRASH_TOOL and running_under_test():
        return None
    try:
        done = subprocess.run([tool, os.fspath(source)], capture_output=True, timeout=TOOL_TIMEOUT_S, shell=False, check=False)
        code = done.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("pack_trash_tool_failed", error=type(exc).__name__)
        code = -1
    if not os.path.lexists(source):
        return TrashResult(os.fspath(home / ".Trash"), "platform")
    log.warning("pack_trash_tool_no_move", returncode=code)
    return None


def _carnivore_trash(source: Path, state_dir: Path, stamp: str) -> TrashResult:
    from src.core.skills.targets import move_to_trash

    root = state_dir / "pack-trash"
    unique = stamp
    n = 1
    while os.path.lexists(root / f"{source.name}-{unique}"):
        n += 1
        unique = f"{stamp}-{n}"
    try:
        moved = move_to_trash(source, root, unique)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            raise TrashRefused(OTHER_VOLUME, "Carnivore's trash is on another volume") from exc
        raise TrashRefused(NO_TRASH, f"could not move the folder: {type(exc).__name__}") from exc
    return TrashResult(os.fspath(moved), "carnivore")


def _freedesktop(source: Path, home: Path, now: datetime, stamp: str) -> TrashResult:
    base = home / ".local" / "share" / "Trash"
    files, info = base / "files", base / "info"
    for folder in (files, info):
        assert_test_write_allowed(folder)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = _free_name(files, source.name, stamp)
    note = info / f"{destination.name}.trashinfo"
    assert_test_write_allowed(note)
    note.write_text(f"[Trash Info]\nPath={quote(os.fspath(source))}\nDeletionDate={now.strftime('%Y-%m-%dT%H:%M:%S')}\n", encoding="utf-8")
    try:
        _rename(source, destination)
    except OSError as exc:
        note.unlink(missing_ok=True)
        if exc.errno == errno.EXDEV:
            raise TrashRefused(OTHER_VOLUME, "the Trash is on another volume") from exc
        raise TrashRefused(NO_TRASH, f"could not move the folder: {type(exc).__name__}") from exc
    return TrashResult(os.fspath(destination), "platform")


def move(path: Path, *, now: datetime, home: Optional[Path] = None, tool: str = MAC_TRASH_TOOL, state_dir: Optional[Path] = None,
         platform: Optional[str] = None) -> TrashResult:
    source = Path(path)
    assert_test_write_allowed(source)
    if source.is_symlink() or not source.is_dir():
        raise TrashRefused(NO_TRASH, "not a real folder")
    home = Path(home) if home is not None else Path.home()
    system, stamp = platform or sys.platform, _stamp(now)
    if system == "darwin":
        result = _with_tool(source, tool, home)
        if result is None:
            try:
                trash = home / ".Trash"
                destination = _free_name(trash, source.name, stamp)
                if not trash.is_dir():
                    raise FileNotFoundError(os.fspath(trash))
                _rename(source, destination)
                result = TrashResult(os.fspath(destination), "platform")
            except OSError as exc:
                log.warning("pack_trash_rename_refused", error=type(exc).__name__)
                from src.config import settings

                result = _carnivore_trash(source, Path(state_dir) if state_dir is not None else Path(settings.get_state_dir()), stamp)
    elif system.startswith("linux"):
        result = _freedesktop(source, home, now, stamp)
    else:
        raise TrashRefused(NO_TRASH, "this computer has no Trash Carnivore can use")
    if os.path.lexists(source):
        raise TrashRefused(NO_TRASH, "the folder is still in place after the move")
    log.info("pack_copy_trashed", kind=result.kind)
    return result

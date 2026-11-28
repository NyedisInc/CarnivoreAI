
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import List, Optional

import structlog

from src.core.retention import constants as K
from src.core.retention.errors import ProtectedPathError
from src.core.retention.paths import RetentionPaths
from src.core.retention.report import SKIPPED, Action

logger = structlog.get_logger()
TASK = "scratch"
OP = "clear_scratch"


def _under(path: Path, root: Path) -> bool:
    try:
        return root.resolve() in path.resolve().parents
    except OSError:
        return False


def _latest_change(folder: Path) -> float:
    newest = 0.0
    for dirpath, dirs, files in os.walk(folder, followlinks=False):
        for name in files + [d for d in dirs if os.path.islink(os.path.join(dirpath, d))]:
            try:
                newest = max(newest, os.lstat(os.path.join(dirpath, name)).st_mtime)
            except OSError:
                continue
    return newest


def _size(folder: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(folder, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
    return total


def _refusal(session: Path, root: Path, live: Optional[set], idle_hours: int, now: float) -> Optional[str]:
    scratchpad = session / K.SCRATCH_SUBDIR
    if scratchpad.is_symlink() or session.is_symlink() or not _under(scratchpad, root):
        return "refused: path does not resolve under the scratch root"
    if live is None:
        return "registry unreadable: running sessions unknown"
    if session.name in live:
        return "conversation is running"
    if now - _latest_change(session) < idle_hours * 3600:
        return f"changed in the last {idle_hours} hours"
    return None


def plan(paths: RetentionPaths, idle_hours: int, now: Optional[float] = None) -> List[Action]:
    root = paths.scratch_root
    if root is None or not root.is_dir() or root.is_symlink():
        return []
    now = time.time() if now is None else now
    live = paths.live_sessions()
    if live is None:
        logger.warning("retention_scratch_registry_unknown")
    actions: List[Action] = []
    for project in sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()):
        for session in sorted(s for s in project.iterdir() if s.is_dir() or s.is_symlink()):
            scratchpad = session / K.SCRATCH_SUBDIR
            if not (scratchpad.is_dir() or scratchpad.is_symlink()):
                continue
            reason = _refusal(session, root, live, idle_hours, now)
            if reason is None and not any(scratchpad.iterdir()):
                continue
            if reason is None:
                actions.append(Action(TASK, OP, scratchpad, None, _size(scratchpad), detail="session is over and idle"))
            elif reason.startswith("refused"):
                actions.append(Action(TASK, OP, scratchpad, None, None, status=SKIPPED, detail=reason))
    return actions


def apply(action: Action, paths: RetentionPaths, idle_hours: int, now: Optional[float] = None) -> str:
    root, scratchpad = paths.scratch_root, action.source
    if root is None or scratchpad.name != K.SCRATCH_SUBDIR:
        raise ProtectedPathError(f"{scratchpad} is not a scratchpad")
    reason = _refusal(scratchpad.parent, root, paths.live_sessions(), idle_hours, time.time() if now is None else now)
    if reason is not None:
        raise ProtectedPathError(f"{scratchpad}: {reason}")
    removed = 0
    for entry in scratchpad.iterdir():
        if entry.is_symlink() or not entry.is_dir():
            entry.unlink()
        else:
            shutil.rmtree(entry)
        removed += 1
    logger.info("retention_scratch_cleared", scratchpad=str(scratchpad), entries=removed)
    return f"removed {removed} entries, no drive copy (throwaway)"

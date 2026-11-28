
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import structlog

from src.core.retention import constants as K
from src.core.retention.drive import Drive
from src.core.retention.report import Action
from src.core.retention.transfer import move_file_verified

logger = structlog.get_logger()
TASK = "logs"
_ROTATED = re.compile(K.LOG_ROTATED_PATTERN)


def _files(log_dir: Path) -> List[Path]:
    if not log_dir.is_dir():
        return []
    return [p for p in log_dir.iterdir() if p.is_file() and not p.is_symlink()]


def _protected(files: List[Path], now: float) -> set:
    if not files:
        return set()
    newest = max(files, key=lambda p: p.stat().st_mtime)
    keep = {newest}
    keep.update(p for p in files if now - p.stat().st_mtime < K.LOG_ACTIVE_WINDOW_SECONDS)
    keep.update(p for p in files if not _ROTATED.search(p.name))
    return keep


def plan(log_dir: Path, drive_root: Path, cap_mb: int, now: float | None = None) -> List[Action]:
    now = time.time() if now is None else now
    files = _files(log_dir)
    cap = cap_mb * 1024 * 1024
    total = sum(p.stat().st_size for p in files)
    if total <= cap:
        return []
    live = _protected(files, now)
    dest_dir = drive_root.joinpath(*K.LOG_DRIVE_DIR)
    actions: List[Action] = []
    for p in sorted((f for f in files if f not in live), key=lambda f: (f.stat().st_mtime, f.name)):
        if total <= cap:
            break
        stat = p.stat()
        stamp = datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y%m%d")
        actions.append(Action(TASK, "move_file", p, dest_dir / f"{p.name}-{stamp}", stat.st_size, detail=f"folder is over {cap_mb} MB"))
        total -= stat.st_size
    if total > cap:
        logger.warning("retention_logs_still_over_cap", log_dir=str(log_dir), cap_mb=cap_mb, remaining_bytes=total)
    return actions


def apply(action: Action, drive: Drive) -> str:
    assert action.dest is not None
    final = move_file_verified(action.source, drive.folder(K.LOG_DRIVE_DIR) / action.dest.name)
    return f"moved to {final}, sha256 verified, source removed"

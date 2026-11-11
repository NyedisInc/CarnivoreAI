
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import List, Optional

import structlog

from src.core import plugin_layout
from src.cplugs.host import registry_files
from src.cplugs.runtime.sandbox import PROFILES_DIR_NAME, profile_path_for

logger = structlog.get_logger()

RETIRED_DIR_NAME = "retired-profiles"
PROFILE_SUFFIX = ".sb"
MAX_NAME_TRIES = 100


def old_profiles_dir(state_dir: Path) -> Path:
    return registry_files.cplugs_dir(state_dir) / PROFILES_DIR_NAME


def dead_profiles(state_dir: Path) -> List[Path]:
    folder = old_profiles_dir(state_dir)
    if not folder.is_dir() or folder.is_symlink():
        return []
    found: List[Path] = []
    for path in sorted(folder.iterdir()):
        if path.suffix != PROFILE_SUFFIX or path.is_symlink() or not path.is_file():
            continue
        live = profile_path_for(plugin_layout.data_root(state_dir, path.stem))
        if live != path:
            found.append(path)
    return found


def destination(state_dir: Path, today: date) -> Path:
    backups = registry_files.backups_newest_first(state_dir)
    if backups:
        return backups[0] / RETIRED_DIR_NAME
    return registry_files.cplugs_dir(state_dir) / RETIRED_DIR_NAME / today.isoformat()


def _free_name(folder: Path, name: str) -> Optional[Path]:
    for n in range(MAX_NAME_TRIES):
        candidate = folder / (name if n == 0 else f"{name}.{n}")
        if not os.path.lexists(candidate):
            return candidate
    return None


def _move_all(files: List[Path], target: Path) -> List[Path]:
    target.mkdir(parents=True, exist_ok=True)
    moved: List[Path] = []
    for path in files:
        dest = _free_name(target, path.name)
        if dest is None:
            logger.warning("plugin_profile_retire_skipped", profile=path.name, reason="no_free_name")
            continue
        try:
            os.rename(path, dest)
        except OSError as exc:
            logger.warning("plugin_profile_retire_failed", profile=path.name, error_type=type(exc).__name__)
            continue
        moved.append(dest)
    return moved


def retire_old_profiles(state_dir: Path, today: Optional[date] = None) -> List[Path]:
    try:
        files = dead_profiles(state_dir)
        if not files:
            return []
        target = destination(state_dir, today or date.today())
        backup = target.parent if target.name == RETIRED_DIR_NAME and target.parent.name.startswith(registry_files.BACKUP_PREFIX) else None
        times = os.stat(backup) if backup is not None else None
        moved = _move_all(files, target)
        if backup is not None and times is not None:
            os.utime(backup, ns=(times.st_atime_ns, times.st_mtime_ns))
    except OSError as exc:
        logger.warning("plugin_profiles_retire_failed", error_type=type(exc).__name__)
        return []
    if moved:
        logger.info("plugin_profiles_retired", count=len(moved), into=str(target))
    return moved

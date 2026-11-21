
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import structlog

from src.core.core_owned_files.registry import is_core_owned

logger = structlog.get_logger()


class PurgeRefused(Exception):
    pass


@dataclass(frozen=True)
class PurgePlan:

    delete: List[Path] = field(default_factory=list)
    kept: List[Path] = field(default_factory=list)


def plan(folder: Path, plugin_id: str) -> PurgePlan:
    if not folder.is_dir():
        return PurgePlan()
    delete: List[Path] = []
    kept: List[Path] = []
    for current, dirs, names in os.walk(folder):
        for name in names:
            path = Path(current) / name
            (kept if is_core_owned(plugin_id, path.relative_to(folder).as_posix()) else delete).append(path)
        delete.extend(Path(current) / d for d in dirs if (Path(current) / d).is_symlink())
    return PurgePlan(sorted(delete), sorted(kept))


def purge(folder: Path, plugin_id: str, plugins_root: Path, key: Optional[str] = None) -> PurgePlan:
    if folder.resolve().parent != plugins_root.resolve() or folder.name != (key or plugin_id):
        raise PurgeRefused(f"{folder} is not the {plugin_id} folder under {plugins_root}")
    carried = plan(folder, plugin_id)
    for path in carried.delete:
        path.unlink()
    for current, _dirs, _names in os.walk(folder, topdown=False):
        if Path(current) != folder and not any(Path(current).iterdir()):
            Path(current).rmdir()
    if not carried.kept and folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    if carried.kept:
        logger.warning("cplug_purge_kept_core_files", cplug=plugin_id, kept=[p.name for p in carried.kept])
    return carried

"""The runtime data a plugin keeps OUTSIDE its own folder, as ``owns.files`` declares it (``docs/cplugs.md`` 1.2a, 3.3).

A purge deletes a plugin's folder ``<state_dir>/cplugs/<id>/`` (``purge_guard``). Some plugins also write elsewhere under the
app state directory (save keeps its restore points in ``time-machine/``); the manifest names those paths and this module prices
and deletes exactly them. Every path is resolved and must stay inside the state directory; a symlink is unlinked, never
followed, so a link planted under a declared path cannot reach a file outside it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List

import structlog

from src.cplugs.host.purge_guard import PurgePlan

logger = structlog.get_logger()


class PurgePathRefused(ValueError):
    """A declared path resolves outside the state directory; nothing was deleted."""


def _inside(state_dir: Path, rel: str) -> Path:
    root = state_dir.resolve()
    target = root / rel
    resolved = target.parent.resolve() / target.name
    if root not in resolved.parents:
        raise PurgePathRefused(f"{rel} resolves outside {state_dir}")
    return resolved


def _collect(target: Path) -> List[Path]:
    delete: List[Path] = []
    if target.is_symlink() or target.is_file():
        delete.append(target)
    elif target.is_dir():
        for current, dirs, names in os.walk(target):
            delete.extend(Path(current) / name for name in names)
            delete.extend(Path(current) / name for name in dirs if (Path(current) / name).is_symlink())
    return delete


def plan_paths(targets: Iterable[Path]) -> PurgePlan:
    delete: List[Path] = []
    for target in targets:
        delete.extend(_collect(target))
    return PurgePlan(sorted(delete), [])


def purge_paths(targets: Iterable[Path]) -> PurgePlan:
    targets = list(targets)
    carried = plan_paths(targets)
    for path in carried.delete:
        path.unlink()
    for target in targets:
        if target.is_dir() and not target.is_symlink():
            for current, _dirs, _names in os.walk(target, topdown=False):
                if not any(Path(current).iterdir()):
                    Path(current).rmdir()
    if carried.delete:
        logger.info("cplug_purge_owned_files", files=len(carried.delete))
    return carried


def plan(state_dir: Path, rels: Iterable[str]) -> PurgePlan:
    return plan_paths([_inside(state_dir, rel) for rel in rels])


def purge(state_dir: Path, rels: Iterable[str]) -> PurgePlan:
    return purge_paths([_inside(state_dir, rel) for rel in rels])

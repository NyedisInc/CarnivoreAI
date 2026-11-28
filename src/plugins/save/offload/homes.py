
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

from src.plugins.save.vault import constants as K
from src.plugins.save.vault import restore
from src.plugins.save.vault.manifest import HOME_CLAUDE, FileEntry, Manifest
from src.plugins.save.vault.units import PlannedFile

PROJECTS_PREFIX: str = "projects/"

HOME_CLAUDE_PROJECTS: str = f"{HOME_CLAUDE}/projects"


class NoProjectsFolder(LookupError):
    pass


def claude_homes(roots: Sequence[Path]) -> Dict[str, Path]:
    if not roots:
        raise NoProjectsFolder("no Claude projects folder is known")
    return {HOME_CLAUDE: Path(roots[0]).parent, HOME_CLAUDE_PROJECTS: Path(roots[0])}


def misplaced(files: Sequence[PlannedFile], homes: Dict[str, Path]) -> Optional[str]:
    destination = restore.homes_destination(homes)
    for planned in files:
        try:
            back = destination(planned)  # type: ignore[arg-type]
        except restore.RestoreError as exc:
            return f"{planned.rel}: a restore has nowhere to put it ({exc})"
        if os.path.realpath(back) != os.path.realpath(planned.path):
            return f"{planned.rel}: a restore would put it in {Path(back).parent}, not where it is now, so it is not offloaded"
    return None


def _transcript_folder(entry: FileEntry) -> Optional[str]:
    if entry.role not in K.MAIN_ROLES or entry.home != HOME_CLAUDE or not entry.rel.startswith(PROJECTS_PREFIX):
        return None
    return entry.rel[len(PROJECTS_PREFIX):].rpartition("/")[0] or None


def recorded_folder(point: Manifest) -> Optional[str]:
    main = point.main()
    return _transcript_folder(main) if main is not None else None


def point_destination(homes: Dict[str, Path], point: Manifest, folder: Optional[str]) -> Callable[[FileEntry], Path]:
    base = restore.homes_destination(homes)
    recorded = recorded_folder(point)
    held = {_transcript_folder(f) for f in point.files}
    if not folder or recorded is None or folder == recorded or folder in held:
        return base
    old_prefix, new_prefix = f"{PROJECTS_PREFIX}{recorded}/", f"{PROJECTS_PREFIX}{folder}/"

    def destination(entry: FileEntry) -> Path:
        if entry.home == HOME_CLAUDE and entry.rel.startswith(old_prefix):
            return base(replace(entry, rel=new_prefix + entry.rel[len(old_prefix):]))
        return base(entry)

    return destination


from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from scripts.backup.errors import BadPhaseId, SourceMissing
from src.core.db_rename.legacy import readable_db_path

DEFAULT_STATE_DIR = Path("~/Library/Application Support/Carnivore").expanduser()
DEFAULT_CONFIG_FILE = Path("~/Library/Application Support/Carnivore Menubar/server/config.json").expanduser()
BACKUP_VOLUME = Path("/Volumes/Backup")
FALLBACK_DIR_NAME = "phase-backups"
SET_PREFIX = "phase-"
MANIFEST_NAME = "MANIFEST.json"
MANIFEST_FORMAT = 1
PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700
_PHASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")

STATE_FILES: Tuple[str, ...] = ("cplugs/state.json",)
STATE_TREES: Tuple[str, ...] = ("cplugs/huddle/files", "cplugs/task_manager/files")


@dataclass(frozen=True)
class DbTarget:

    name: str
    candidates: Tuple[str, ...]
    required: bool


DB_TARGETS: Tuple[DbTarget, ...] = (
    DbTarget("carnivore.db", (), True),
    DbTarget("huddle.db", ("cplugs/huddle/huddle.db", "huddle.db"), False),
)


def validate_phase_id(phase: str) -> str:
    if not _PHASE_ID.match(phase):
        raise BadPhaseId(f"phase id {phase!r} must be 1 to 32 characters of letters, digits, '.', '_' or '-'")
    return phase


def resolve_state_dir(explicit: Optional[str]) -> Path:
    chosen = explicit or os.environ.get("CARNIVORE_STATE_DIR") or os.environ.get("CLOUDE_STATE_DIR")
    path = Path(chosen).expanduser() if chosen else DEFAULT_STATE_DIR
    if not path.is_dir():
        raise SourceMissing(f"state directory {path} does not exist")
    return path


def resolve_database(state_dir: Path, target: DbTarget) -> Optional[Path]:
    if target.candidates:
        for rel in target.candidates:
            path = state_dir / rel
            if path.is_file() and path.stat().st_size > 0:
                return path
        found = None
    else:
        path = readable_db_path(state_dir)
        found = path if path.is_file() and path.stat().st_size > 0 else None
    if found is None and target.required:
        raise SourceMissing(f"required database {target.name} not found under {state_dir}")
    return found


def default_destination(state_dir: Path) -> Path:
    return BACKUP_VOLUME if BACKUP_VOLUME.is_dir() else state_dir / FALLBACK_DIR_NAME

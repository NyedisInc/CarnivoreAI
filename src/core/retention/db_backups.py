
from __future__ import annotations

from pathlib import Path
from typing import List

from src.core.db_backup import BACKUP_SUFFIX
from src.core.product_identity import DB_BACKUP_PREFIX, LEGACY_DB_BACKUP_PREFIXES
from src.core.retention import constants as K
from src.core.retention.drive import Drive
from src.core.retention.report import Action
from src.core.retention.transfer import move_file_verified

TASK = "db_backups"
_PREFIXES = (DB_BACKUP_PREFIX, *LEGACY_DB_BACKUP_PREFIXES)


def list_backups(state_dir: Path) -> List[Path]:
    if not state_dir.is_dir():
        return []
    found = [p for p in state_dir.iterdir()
             if p.is_file() and not p.is_symlink() and p.name.endswith(BACKUP_SUFFIX) and p.name.startswith(_PREFIXES)]
    return sorted(found, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)


def plan(state_dir: Path, drive_root: Path, keep: int) -> List[Action]:
    dest_dir = drive_root.joinpath(*K.DB_BACKUP_DRIVE_DIR)
    return [Action(TASK, "move_file", p, dest_dir / p.name, p.stat().st_size, detail=f"older than the newest {keep}")
            for p in list_backups(state_dir)[max(keep, 0):]]


def apply(action: Action, drive: Drive) -> str:
    assert action.dest is not None
    final = move_file_verified(action.source, drive.folder(K.DB_BACKUP_DRIVE_DIR) / action.dest.name)
    return f"moved to {final}, sha256 verified, source removed"

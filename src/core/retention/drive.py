
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from src.core.retention import constants as K
from src.core.retention.errors import DriveNotReadyError
from src.core.retention.paths import RetentionPaths


@dataclass(frozen=True)
class Drive:

    root: Path

    def folder(self, parts: Tuple[str, ...]) -> Path:
        return self.root.joinpath(*parts)


def require_drive(paths: RetentionPaths) -> Drive:
    root = paths.drive_root
    if not root.is_dir() or not paths.is_mount(root):
        raise DriveNotReadyError(f"{root} is not mounted")
    if not (root / K.DRIVE_MARKER_FILE).is_file() or not (root / K.DRIVE_MARKER_DIR).is_dir():
        raise DriveNotReadyError(f"{root} is mounted but is not the expected backup volume")
    return Drive(root=root)


from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from src.core.project_move.paths import is_within

SF_DATALESS = 0x40000000

ICLOUD_DRIVE_DIR = ("Library", "Mobile Documents")


def icloud_root() -> str:
    return os.path.realpath(Path.home().joinpath(*ICLOUD_DRIVE_DIR))


def in_icloud(path: str) -> bool:
    return is_within(path, icloud_root())


def is_dataless(path: Path) -> bool:
    return bool(getattr(os.lstat(path), "st_flags", 0) & SF_DATALESS)


def read_text_if_local(path: Path) -> Optional[str]:
    if is_dataless(path):
        return None
    return path.read_text(encoding="utf-8")

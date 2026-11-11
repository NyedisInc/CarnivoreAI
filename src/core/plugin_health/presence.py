
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Union

PRESENT = "present"
GONE = "gone"
UNREADABLE = "unreadable"


def folder_presence(path: Union[str, Path]) -> str:
    target = Path(path)
    try:
        info = os.stat(target)
    except FileNotFoundError:
        return _absent_or_unseen(target)
    except OSError:
        return UNREADABLE
    if not stat.S_ISDIR(info.st_mode):
        return UNREADABLE
    try:
        with os.scandir(target):
            return PRESENT
    except OSError:
        return UNREADABLE


def _absent_or_unseen(target: Path) -> str:
    parent = target.parent
    try:
        with os.scandir(parent) as listing:
            names = {entry.name for entry in listing}
    except OSError:
        return UNREADABLE
    if target.name in names or f".{target.name}.icloud" in names:
        return UNREADABLE
    return GONE

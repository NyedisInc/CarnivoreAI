
from __future__ import annotations

import secrets
import shutil
import time
from pathlib import Path
from typing import Optional

import structlog

from src.cplugs.crate import constants as K

logger = structlog.get_logger()


def extract_root(work: Path) -> Path:
    root = Path(work) / K.EXTRACT_DIR
    root.mkdir(mode=K.FOLDER_MODE, parents=True, exist_ok=True)
    return root


def new_extract_dest(work: Path) -> Path:
    return extract_root(work) / secrets.token_hex(K.EXTRACT_ID_HEX)


def new_drill_scratch(work: Path) -> Path:
    folder = extract_root(work) / f"{K.DRILL_PREFIX}{secrets.token_hex(K.EXTRACT_ID_HEX)}"
    folder.mkdir(mode=K.FOLDER_MODE)
    return folder


def remove_folder(folder: Path) -> None:
    if folder.parent.name != K.EXTRACT_DIR:
        raise ValueError(f"{folder} is not a crate scratch folder")
    if folder.is_dir() and not folder.is_symlink():
        shutil.rmtree(folder)


def prune_extracts(work: Path, now: Optional[float] = None) -> int:
    root = Path(work) / K.EXTRACT_DIR
    if not root.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - K.EXTRACT_KEEP_S
    removed = 0
    for entry in root.iterdir():
        try:
            if entry.is_dir() and not entry.is_symlink() and entry.lstat().st_mtime < cutoff:
                shutil.rmtree(entry)
                removed += 1
        except OSError as exc:
            logger.warning("crate_extract_prune_failed", folder=entry.name, error_type=type(exc).__name__)
    return removed


from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

SCRATCH_DIR_PREFIX = "carnivore-scratch-"

_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def scratch_root() -> Path:
    return Path(os.path.realpath(tempfile.gettempdir()))


def mint_scratch_dir(session_id: str, *, base_dir: Optional[Path] = None) -> str:
    root = Path(os.path.realpath(base_dir)) if base_dir is not None else scratch_root()
    slug = _SAFE_ID_RE.sub("", session_id).strip("_-") or "scratch"
    target = root / f"{SCRATCH_DIR_PREFIX}{slug}"
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    return os.path.realpath(target)


def is_managed_scratch_dir(path: Optional[str], *, base_dir: Optional[Path] = None) -> bool:
    if not path or not isinstance(path, str):
        return False
    root = Path(os.path.realpath(base_dir)) if base_dir is not None else scratch_root()
    try:
        resolved = Path(os.path.realpath(os.path.expanduser(path)))
    except OSError:
        return False
    return resolved.parent == root and resolved.name.startswith(SCRATCH_DIR_PREFIX) and len(resolved.name) > len(SCRATCH_DIR_PREFIX)


def cleanup_scratch_dir_best_effort(path: Optional[str], *, base_dir: Optional[Path] = None) -> bool:
    if not is_managed_scratch_dir(path, base_dir=base_dir):
        return False
    resolved = Path(os.path.realpath(os.path.expanduser(path or "")))
    if not resolved.exists():
        return False
    try:
        shutil.rmtree(resolved)
        logger.info("disposable_scratch_dir_cleaned", path=str(resolved))
        return True
    except OSError as exc:
        logger.warning("disposable_scratch_dir_cleanup_failed", path=str(resolved), error=str(exc))
        return False

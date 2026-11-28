
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Sequence

import structlog

from src.plugins.save.offload import constants as C
from src.plugins.sdk.destination_rules import ICLOUD_DRIVE

logger = structlog.get_logger()


def icloud_root() -> Path:
    return Path(os.path.realpath(os.path.expanduser(ICLOUD_DRIVE)))


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def blocker_of(path: Path, root: Optional[Path] = None) -> Optional[str]:
    try:
        real = Path(os.path.realpath(path, strict=False))
        base = root if root is not None else icloud_root()
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("offload_icloud_unresolvable", path=str(path), error_type=type(exc).__name__, error=str(exc)[:200])
        return C.BLOCKER_ICLOUD_UNKNOWN
    return C.BLOCKER_ICLOUD_PATH if _under(real, base) else None


def blockers(folders: Sequence[Path], root: Optional[Path] = None) -> List[str]:
    return sorted({code for code in (blocker_of(Path(f), root) for f in folders) if code})

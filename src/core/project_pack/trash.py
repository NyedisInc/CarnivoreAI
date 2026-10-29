
from __future__ import annotations

import os
import subprocess
from typing import Callable, Sequence

import structlog

from src.core.project_pack import constants as K

logger = structlog.get_logger()

TrashFn = Callable[[Sequence[str]], None]


class TrashError(Exception):
    pass


def trash_paths(paths: Sequence[str]) -> None:
    paths = [str(p) for p in paths]
    if not paths:
        return
    if not os.access(K.TRASH_BIN, os.X_OK):
        raise TrashError(f"{K.TRASH_BIN} is not available (it ships with macOS 15 and later)")
    done = subprocess.run([K.TRASH_BIN, "-s", *paths], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise TrashError(f"trash exited {done.returncode}: {(done.stderr or done.stdout).strip()[:300]}")
    left = [p for p in paths if os.path.lexists(p)]
    if left:
        raise TrashError(f"still in place after trash: {left}")
    logger.info("project_pack_trashed", count=len(paths), first=os.path.basename(paths[0]))

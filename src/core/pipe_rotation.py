
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()

__all__ = ["rotation_reason", "truncate_in_place"]


def rotation_reason(
    size_bytes: int,
    age_hours: float,
    max_bytes: int,
    max_age_hours: float,
) -> Optional[str]:
    if size_bytes > max_bytes:
        return "size"
    if age_hours > max_age_hours:
        return "age"
    return None


def truncate_in_place(pipe_path: Path, read_fd: int) -> bool:
    try:
        os.truncate(str(pipe_path), 0)
    except OSError as exc:
        logger.warning(
            "tmux_pipe_truncate_failed", path=str(pipe_path), error=str(exc)
        )
        return False

    try:
        os.lseek(read_fd, 0, os.SEEK_SET)
    except OSError as exc:
        logger.error(
            "tmux_pipe_reseek_failed", path=str(pipe_path), error=str(exc)
        )
        return False

    return True

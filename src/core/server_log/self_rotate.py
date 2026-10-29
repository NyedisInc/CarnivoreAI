
from __future__ import annotations

import asyncio
import os
import stat
from contextlib import suppress
from pathlib import Path
from typing import Optional

import structlog

from src.core.server_log.locate import menubar_log_files, own_log_path

logger = structlog.get_logger()

MAX_BYTES = 50 * 1024 * 1024
BACKUP_COUNT = 5
CHECK_INTERVAL_S = 60.0
BACKUP_MODE = 0o600
_COPY_CHUNK = 1024 * 1024
_OPEN_FLAGS = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
_TEMP_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


def _shift_backups(path: Path, backups: int) -> None:
    for index in range(backups - 1, 0, -1):
        source = Path(f"{path}.{index}")
        if source.exists():
            os.replace(source, f"{path}.{index + 1}")


def _copy_to_backup(fd: int, path: Path) -> int:
    backup = Path(f"{path}.1")
    temp = path.with_name(f".{path.name}.rotate.{os.getpid()}.tmp")
    out = os.open(temp, _TEMP_FLAGS, BACKUP_MODE)
    copied = 0
    try:
        os.fchmod(out, BACKUP_MODE)
        while True:
            chunk = os.pread(fd, _COPY_CHUNK, copied)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                view = view[os.write(out, view):]
            copied += len(chunk)
        os.fsync(out)
    except BaseException:
        os.close(out)
        with suppress(OSError):
            os.unlink(temp)
        raise
    os.close(out)
    os.replace(temp, backup)
    return copied


def rotate_if_needed(path: Path, max_bytes: int = MAX_BYTES, backups: int = BACKUP_COUNT) -> bool:
    try:
        fd = os.open(path, _OPEN_FLAGS)
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("server_log_rotate_refused", reason=exc.strerror or type(exc).__name__)
        return False
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            logger.warning("server_log_rotate_refused", reason="not a regular file we own")
            return False
        if info.st_size <= max_bytes:
            return False
        moved = 0
        if backups > 0:
            _shift_backups(path, backups)
            moved = _copy_to_backup(fd, path)
        os.ftruncate(fd, 0)
    finally:
        os.close(fd)
    logger.info("server_log_rotated", moved_bytes=moved, backup=f"{path.name}.1" if backups > 0 else None)
    return True


def applicable_path() -> Optional[Path]:
    path = own_log_path()
    return path if path is not None and path in menubar_log_files() else None


async def run(path: Path, interval_s: float = CHECK_INTERVAL_S, max_bytes: int = MAX_BYTES,
              backups: int = BACKUP_COUNT) -> None:
    while True:
        try:
            await asyncio.to_thread(rotate_if_needed, path, max_bytes, backups)
        except OSError as exc:
            logger.warning("server_log_rotate_failed", error=str(exc), error_type=type(exc).__name__)
        await asyncio.sleep(interval_s)


def start() -> Optional["asyncio.Task[None]"]:
    path = applicable_path()
    if path is None:
        return None
    return asyncio.create_task(run(path))

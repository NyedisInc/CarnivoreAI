from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

import structlog

logger = structlog.get_logger()

PRIVATE_DIR_MODE = 0o700

_FOREIGN_WRITE_BITS = stat.S_IWGRP | stat.S_IWOTH

_DIR_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

_TEMP_OPEN_FLAGS = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
)


class SafeFileWriteError(OSError):
    pass


class UnsafeFileTargetError(SafeFileWriteError):

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"refusing to write {path}: {reason.replace('_', ' ')}")
        self.path = path
        self.reason = reason


def _refuse(path: Path, reason: str) -> UnsafeFileTargetError:
    logger.error("safe_file_write_refused", path=str(path), reason=reason)
    return UnsafeFileTargetError(str(path), reason)


def _open_private_dir(directory: Path) -> int:
    try:
        directory.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.mkdir(directory, PRIVATE_DIR_MODE)
        except FileExistsError:
            pass
        before = os.lstat(directory)
    except OSError as exc:
        logger.error("safe_file_write_dir_failed", path=str(directory), error=str(exc))
        raise SafeFileWriteError(f"cannot prepare {directory}: {exc}") from exc
    if stat.S_ISLNK(before.st_mode):
        raise _refuse(directory, "directory_is_symlink")
    if not stat.S_ISDIR(before.st_mode):
        raise _refuse(directory, "directory_not_a_directory")
    try:
        dir_fd = os.open(directory, _DIR_OPEN_FLAGS)
    except OSError as exc:
        raise _refuse(directory, "directory_is_symlink") from exc
    try:
        info = os.fstat(dir_fd)
        if not stat.S_ISDIR(info.st_mode):
            raise _refuse(directory, "directory_not_a_directory")
        if info.st_uid != os.geteuid():
            raise _refuse(directory, "directory_foreign_owner")
        if info.st_mode & _FOREIGN_WRITE_BITS:
            raise _refuse(directory, "directory_foreign_writable")
    except BaseException:
        os.close(dir_fd)
        raise
    return dir_fd


def _still_same_dir(directory: Path, dir_fd: int) -> bool:
    try:
        now = os.lstat(directory)
    except OSError:
        return False
    held = os.fstat(dir_fd)
    return (
        stat.S_ISDIR(now.st_mode)
        and now.st_ino == held.st_ino
        and now.st_dev == held.st_dev
    )


def _check_final_name(directory: Path, name: str, dir_fd: int) -> None:
    try:
        existing = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise SafeFileWriteError(f"cannot inspect {directory / name}: {exc}") from exc
    if stat.S_ISLNK(existing.st_mode):
        raise _refuse(directory / name, "target_is_symlink")
    if not stat.S_ISREG(existing.st_mode):
        raise _refuse(directory / name, "target_not_a_regular_file")


def write_private_file(directory: Path, name: str, data: bytes, mode: int) -> Path:
    if not name or os.sep in name or name in (".", ".."):
        raise ValueError(f"not a plain file name: {name!r}")
    target = directory / name
    dir_fd = _open_private_dir(directory)
    tmp_name = f".{name}.{secrets.token_hex(8)}.tmp"
    tmp_created = False
    try:
        _check_final_name(directory, name, dir_fd)
        try:
            fd = os.open(tmp_name, _TEMP_OPEN_FLAGS, mode, dir_fd=dir_fd)
            tmp_created = True
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fchmod(stream.fileno(), mode)
                os.fsync(stream.fileno())
        except OSError as exc:
            logger.error("safe_file_write_failed", path=str(target), error=str(exc))
            raise SafeFileWriteError(f"cannot write {target}: {exc}") from exc
        if not _still_same_dir(directory, dir_fd):
            raise _refuse(directory, "directory_is_symlink")
        try:
            os.replace(directory / tmp_name, target)
            tmp_created = False
            os.fsync(dir_fd)
        except OSError as exc:
            logger.error("safe_file_write_failed", path=str(target), error=str(exc))
            raise SafeFileWriteError(f"cannot write {target}: {exc}") from exc
        return target
    finally:
        if tmp_created:
            try:
                os.unlink(tmp_name, dir_fd=dir_fd)
            except OSError as exc:
                logger.warning("safe_file_write_tmp_left", path=str(directory / tmp_name), error=str(exc))
        os.close(dir_fd)

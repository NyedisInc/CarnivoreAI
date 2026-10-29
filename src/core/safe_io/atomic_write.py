
from __future__ import annotations

import contextlib
import errno
import os
from pathlib import Path
from typing import Optional, Union

import structlog

from src.core.unique_tmp_path import unique_tmp_path

logger = structlog.get_logger(__name__)

_FSYNC_UNSUPPORTED = frozenset({errno.EINVAL, errno.ENOTSUP, errno.ENOSYS})

DEFAULT_PARENT_MODE = 0o777

PathLike = Union[str, "os.PathLike[str]"]


def _fsync_directory(directory: Path) -> None:
    with contextlib.suppress(OSError):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _fsync_file(fd: int, target: Path, tolerate_unsupported: bool) -> None:
    try:
        os.fsync(fd)
    except OSError as exc:
        if not tolerate_unsupported or exc.errno not in _FSYNC_UNSUPPORTED:
            raise
        logger.debug("atomic_write_fsync_unsupported", path=str(target), error=str(exc))


def atomic_write_bytes(
    path: PathLike,
    data: bytes,
    *,
    mode: Optional[int] = None,
    parent_mode: Optional[int] = None,
    tolerate_fsync_unsupported: bool = False,
) -> None:
    target = Path(path)
    if parent_mode is not None:
        target.parent.mkdir(parents=True, exist_ok=True, mode=parent_mode)
    tmp = unique_tmp_path(target)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666 if mode is None else mode)
        with os.fdopen(fd, "wb") as handle:
            if mode is not None:
                os.fchmod(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            _fsync_file(handle.fileno(), target, tolerate_fsync_unsupported)
        os.replace(tmp, target)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
    _fsync_directory(target.parent)


def atomic_write_text(
    path: PathLike,
    text: str,
    *,
    mode: Optional[int] = None,
    parent_mode: Optional[int] = None,
    tolerate_fsync_unsupported: bool = False,
) -> None:
    atomic_write_bytes(
        path, text.encode("utf-8"), mode=mode, parent_mode=parent_mode,
        tolerate_fsync_unsupported=tolerate_fsync_unsupported,
    )

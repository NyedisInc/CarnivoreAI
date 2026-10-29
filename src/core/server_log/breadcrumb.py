
from __future__ import annotations

import errno
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Dict, Iterable, Optional

import structlog

from src.core.attention.record_identity import read_lstarts
from src.core.conversation_writers import same_process_start
from src.core.safe_file_write import write_private_file
from src.core.server_log.locate import own_log_path, validated_log_path

logger = structlog.get_logger()

BREADCRUMB_NAME = "server-log-location.json"
BREADCRUMB_MODE = 0o600
MAX_BREADCRUMB_BYTES = 4096
_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC

LIVE, STALE, UNVERIFIED = "live", "stale", "unverified"

Lstarts = Callable[[Iterable[int]], Optional[Dict[int, str]]]


class BreadcrumbError(Exception):
    pass


class BreadcrumbMissing(BreadcrumbError):
    pass


class BreadcrumbRefused(BreadcrumbError):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LocatedLog:

    path: Path
    pid: int
    started_at: Optional[str]
    writer: Optional[int]
    status: str


def publish(state_dir: Path, *, lstarts: Lstarts = read_lstarts) -> Optional[Path]:
    log_path = own_log_path()
    if log_path is None:
        return None
    pid = os.getpid()
    found = lstarts([pid]) or {}
    payload = {"path": str(log_path), "pid": pid, "started_at": found.get(pid), "writer": os.getppid()}
    try:
        return write_private_file(Path(state_dir), BREADCRUMB_NAME, json.dumps(payload).encode("utf-8"),
                                  BREADCRUMB_MODE)
    except OSError as exc:
        logger.warning("server_log_breadcrumb_write_failed", error=str(exc), error_type=type(exc).__name__)
        return None


def _open_owned_regular(path: Path, what: str) -> int:
    try:
        fd = os.open(path, _OPEN_FLAGS)
    except FileNotFoundError as exc:
        raise BreadcrumbRefused(f"{what}_missing") from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise BreadcrumbRefused(f"{what}_symlink") from exc
        raise
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        os.close(fd)
        raise BreadcrumbRefused(f"{what}_not_own_regular_file")
    return fd


def open_log_nofollow(path: Path) -> BinaryIO:
    checked = validated_log_path(str(path))
    if checked is None:
        raise BreadcrumbRefused("log_path_not_allowed")
    parent = os.lstat(checked.parent)
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid():
        raise BreadcrumbRefused("log_dir_not_own_directory")
    return os.fdopen(_open_owned_regular(checked, "log"), "rb")


def _load(state_dir: Path) -> dict:
    try:
        fd = _open_owned_regular(Path(state_dir) / BREADCRUMB_NAME, "breadcrumb")
    except BreadcrumbRefused as exc:
        if exc.reason == "breadcrumb_missing":
            raise BreadcrumbMissing(str(state_dir)) from exc
        raise
    with os.fdopen(fd, "rb") as handle:
        if os.fstat(handle.fileno()).st_mode & 0o022:
            raise BreadcrumbRefused("breadcrumb_writable_by_others")
        raw = handle.read(MAX_BREADCRUMB_BYTES + 1)
    if len(raw) > MAX_BREADCRUMB_BYTES:
        raise BreadcrumbRefused("breadcrumb_too_big")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BreadcrumbRefused("breadcrumb_not_json") from exc
    if not isinstance(data, dict):
        raise BreadcrumbRefused("breadcrumb_not_json")
    return data


def _status(pid: int, started_at: Optional[str], lstarts: Lstarts) -> str:
    found = lstarts([pid])
    if found is None:
        return UNVERIFIED
    now = found.get(pid)
    if now is None or not started_at or not same_process_start(now, started_at):
        return STALE
    return LIVE


def read_breadcrumb(state_dir: Path, *, lstarts: Lstarts = read_lstarts) -> LocatedLog:
    data = _load(state_dir)
    pid, started_at, writer = data.get("pid"), data.get("started_at"), data.get("writer")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise BreadcrumbRefused("breadcrumb_bad_pid")
    if started_at is not None and not isinstance(started_at, str):
        raise BreadcrumbRefused("breadcrumb_bad_started_at")
    path = validated_log_path(data.get("path"))
    if path is None:
        raise BreadcrumbRefused("log_path_not_allowed")
    with open_log_nofollow(path):
        pass
    return LocatedLog(
        path=path,
        pid=pid,
        started_at=started_at,
        writer=writer if isinstance(writer, int) and not isinstance(writer, bool) else None,
        status=_status(pid, started_at, lstarts),
    )

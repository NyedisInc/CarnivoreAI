
from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import stat
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

import structlog

logger = structlog.get_logger(__name__)

# state directory
TOKEN_FILENAME = "tui_auth.json"
LOCK_FILENAME = "tui_auth.lock"
LOCK_TIMEOUT_SECONDS = 15.0
_LOCK_POLL_SECONDS = 0.05


class LockBusy(Exception):
    pass


@dataclass(frozen=True)
class TokenPair:

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    access_expires_at: float

    def access_fresh(self, margin: float = 30.0) -> bool:
        return self.access_expires_at - time.time() > margin


class TokenStore:

    def __init__(self, directory: Path) -> None:
        self.path = directory / TOKEN_FILENAME
        self.lock_path = directory / LOCK_FILENAME

    def _read_checked(self) -> Optional[bytes]:
        """The token file's bytes, or None (with a logged reason, never contents) when it is unsafe.

        Opens with O_NOFOLLOW and O_NONBLOCK (a symlink or a FIFO cannot hang or redirect us), then
        requires a regular file owned by this user with no group or world access.
        """
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        except OSError as exc:
            reason = "symlink" if exc.errno == errno.ELOOP else "open_failed"
            logger.warning("tui_token_file_rejected", reason=reason)
            return None
        try:
            st = os.fstat(fd)
            reason = (
                "not_regular_file" if not stat.S_ISREG(st.st_mode)
                else "other_owner" if st.st_uid != os.geteuid()
                else "group_or_world_access" if st.st_mode & 0o077
                else ""
            )
            if reason:
                logger.warning("tui_token_file_rejected", reason=reason)
                return None
            with os.fdopen(fd, "rb", closefd=False) as handle:
                return handle.read()
        finally:
            os.close(fd)

    def load(self) -> Optional[TokenPair]:
        try:
            raw = self._read_checked()
            if raw is None:
                return None
            data = json.loads(raw.decode("utf-8"))
            return TokenPair(
                access_token=str(data["access_token"]),
                refresh_token=str(data["refresh_token"]),
                access_expires_at=float(data["access_expires_at"]),
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("tui_token_file_unreadable", error=type(exc).__name__)
            return None

    def save(self, pair: TokenPair) -> None:
        payload = json.dumps(
            {
                "access_token": pair.access_token,
                "refresh_token": pair.refresh_token,
                "access_expires_at": pair.access_expires_at,
            }
        ).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".tui_auth.", suffix=".tmp")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
            self._fsync_directory()
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise

    def _fsync_directory(self) -> None:
        dir_fd = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def clear(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()

    def clear_if(self, refresh_token: str) -> bool:
        current = self.load()
        if current is None or current.refresh_token != refresh_token:
            return False
        self.clear()
        return True

    @contextlib.contextmanager
    def locked(self, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        logger.warning("tui_token_lock_busy")
                        raise LockBusy() from None
                    time.sleep(_LOCK_POLL_SECONDS)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

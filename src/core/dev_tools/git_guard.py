
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable, Optional

_YES_TTL_S = 300.0
_NO_TTL_S = 15.0
_COLD_WAIT_S = 0.5
_SHIM_DIR = "/usr/bin"
_CLT_DIR = "/Library/Developer/CommandLineTools"
_XCODE_DIR = "/Applications/Xcode.app/Contents/Developer"


class _TtlProbe:

    def __init__(self, probe: Callable[[], bool]) -> None:
        self._probe = probe
        self._lock = threading.Lock()
        self._probe_lock = threading.Lock()
        self._cached: Optional[bool] = None
        self._checked_at = 0.0

    def get(self) -> bool:
        fresh, last = self._read()
        if fresh is not None:
            return fresh
        if not self._probe_lock.acquire(blocking=False):
            if last is not None:
                return last
            if not self._probe_lock.acquire(timeout=_COLD_WAIT_S):
                return False
            fresh, _ = self._read()
            if fresh is not None:
                self._probe_lock.release()
                return fresh
        try:
            answer = self._probe()
            with self._lock:
                self._cached = answer
                self._checked_at = time.monotonic()
            return answer
        finally:
            self._probe_lock.release()

    def _read(self) -> "tuple[Optional[bool], Optional[bool]]":
        with self._lock:
            if self._cached is None:
                return None, None
            ttl = _YES_TTL_S if self._cached else _NO_TTL_S
            fresh = time.monotonic() - self._checked_at <= ttl
            return (self._cached if fresh else None), self._cached

    def drop(self) -> None:
        with self._lock:
            self._cached = None


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _developer_dir_has_tool(directory: str, tool: str) -> bool:
    return bool(directory) and os.access(os.path.join(directory, "usr", "bin", tool), os.X_OK)


def _developer_dir_has_git(directory: str) -> bool:
    return _developer_dir_has_tool(directory, "git")


def _xcode_select_dir() -> str:
    try:
        done = subprocess.run(["/usr/bin/xcode-select", "-p"], capture_output=True, text=True, timeout=5, check=False,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def tool_available(tool: str) -> bool:
    found = shutil.which(tool)
    if not found:
        return False
    if not _is_macos() or os.path.dirname(os.path.normpath(found)) != _SHIM_DIR:
        return True
    return _developer_dirs_have(tool)


def _developer_dirs_have(tool: str, honor_developer_dir: bool = True) -> bool:
    candidates = (os.environ.get("DEVELOPER_DIR", "") if honor_developer_dir else "", _CLT_DIR, _XCODE_DIR)
    has = _developer_dir_has_git if tool == "git" else (lambda d: _developer_dir_has_tool(d, tool))
    return any(has(d) for d in candidates) or has(_xcode_select_dir())


def _probe() -> bool:
    return tool_available("git")


def _probe_usr_bin() -> bool:
    if not _is_macos():
        return os.access(os.path.join(_SHIM_DIR, "git"), os.X_OK)
    return _developer_dirs_have("git", honor_developer_dir=False)


_git_probe = _TtlProbe(lambda: _probe())
_usr_bin_probe = _TtlProbe(lambda: _probe_usr_bin())


def git_available() -> bool:
    return _git_probe.get()


def usr_bin_git_available() -> bool:
    return _usr_bin_probe.get()


def recheck() -> bool:
    _git_probe.drop()
    _usr_bin_probe.drop()
    return git_available()

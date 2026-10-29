
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Optional

_YES_TTL_S = 300.0
_NO_TTL_S = 15.0
_SHIM_DIR = "/usr/bin"
_CLT_DIR = "/Library/Developer/CommandLineTools"
_XCODE_DIR = "/Applications/Xcode.app/Contents/Developer"

_lock = threading.Lock()
_probe_lock = threading.Lock()
_cached: Optional[bool] = None
_checked_at = 0.0


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
    candidates = (os.environ.get("DEVELOPER_DIR", ""), _CLT_DIR, _XCODE_DIR)
    has = _developer_dir_has_git if tool == "git" else (lambda d: _developer_dir_has_tool(d, tool))
    return any(has(d) for d in candidates) or has(_xcode_select_dir())


def _probe() -> bool:
    return tool_available("git")


def git_available() -> bool:
    global _cached, _checked_at
    with _lock:
        ttl = _YES_TTL_S if _cached else _NO_TTL_S
        if _cached is not None and time.monotonic() - _checked_at <= ttl:
            return _cached
        last = bool(_cached)
    if not _probe_lock.acquire(blocking=False):
        return last
    try:
        answer = _probe()
        with _lock:
            _cached = answer
            _checked_at = time.monotonic()
        return answer
    finally:
        _probe_lock.release()


def recheck() -> bool:
    global _cached
    with _lock:
        _cached = None
    return git_available()

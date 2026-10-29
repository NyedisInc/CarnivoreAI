
from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import structlog

from src.core.attention.registry_read import pid_is_running
from src.config.provider_accounts import DEFAULT_CLAUDE_CONFIG_DIR

logger = structlog.get_logger()

__all__ = [
    "BUSY_CLAUDE_RUNNING",
    "BUSY_RECHECK_SECONDS",
    "BUSY_REFRESH_LOCK",
    "LOCK_FRESH_SECONDS",
    "PRE_EXPIRY_LEAD_SECONDS",
    "busy_reason",
    "refresh_due_at",
]

PRE_EXPIRY_LEAD_SECONDS = 240.0

BUSY_RECHECK_SECONDS = 30.0

LOCK_FRESH_SECONDS = 60.0

REFRESH_LOCK_NAME = ".oauth_refresh.lock"

SESSIONS_DIRNAME = "sessions"

SCAN_LIMIT = 128

BUSY_CLAUDE_RUNNING = "claude_running"
BUSY_REFRESH_LOCK = "refresh_lock_held"


def refresh_due_at(expires_at: datetime) -> datetime:
    return expires_at - timedelta(seconds=PRE_EXPIRY_LEAD_SECONDS)


def busy_recheck_at(now: datetime, expires_at: datetime) -> Optional[datetime]:
    recheck = now + timedelta(seconds=BUSY_RECHECK_SECONDS)
    return recheck if recheck < expires_at else None


def claude_dir_for(profile: Optional[str]) -> str:
    return profile if profile is not None else os.path.expanduser(DEFAULT_CLAUDE_CONFIG_DIR)


def _lock_paths(claude_dir: str) -> Tuple[str, str]:
    return (
        os.path.join(claude_dir, REFRESH_LOCK_NAME),
        os.path.realpath(claude_dir) + ".lock",
    )


def _lock_is_fresh(path: str, now_epoch: float) -> bool:
    try:
        mtime = os.stat(path).st_mtime
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return now_epoch - mtime < LOCK_FRESH_SECONDS


def _pid_config_dir(pid: int) -> Optional[str]:
    """The config dir one process runs with, read from that pid's env only.

    Why: since b178d3e0 every managed profile's ``sessions`` is a symlink
      to ``~/.claude/sessions``, which registers EVERY live claude, so the
      registry alone cannot say whose process it is (the record carries no
      config dir). Only the one variable is extracted, never printed.
    Inputs: pid (int).
    Output: str | None - the realpath of ``CLAUDE_CONFIG_DIR`` (the default
      ``~/.claude`` when the process has none); None when the env could not
      be measured (ps failed, or the process is not ours to read).
    Example: _pid_config_dir(51292)  # '/Users/a/.carnivore/accounts/c1'
    """
    try:
        out = subprocess.run(
            ["ps", "eww", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    words = out.split()
    if not any(w.startswith(("PATH=", "HOME=")) for w in words):
        return None
    for word in words:
        if word.startswith("CLAUDE_CONFIG_DIR="):
            return os.path.realpath(word[len("CLAUDE_CONFIG_DIR="):])
    return os.path.realpath(os.path.expanduser(DEFAULT_CLAUDE_CONFIG_DIR))


def live_claude_pids(claude_dir: str) -> List[int]:
    """Pids of claude processes registered under this profile and not dead.

    Description: a pid measured gone is dropped; one that could not be
      measured is KEPT, per the module docstring. A pid whose config dir
      is measured and is ANOTHER profile is dropped (the registry is
      shared). A missing directory is an empty answer.
    Inputs: claude_dir (str) - absolute.
    Output: list[int].
    Example: live_claude_pids("/Users/a/.carnivore/accounts/c1")  # [51292]
    """
    base = os.path.join(claude_dir, SESSIONS_DIRNAME)
    try:
        names = sorted(
            entry.name for entry in os.scandir(base) if entry.name.endswith(".json")
        )
    except OSError:
        return []
    pids: List[int] = []
    for name in names[:SCAN_LIMIT]:
        stem = name[: -len(".json")]
        if not stem.isdigit():
            continue
        pid = int(stem)
        if pid_is_running(pid) is False:
            continue
        owner = _pid_config_dir(pid)
        if owner is None or owner == os.path.realpath(claude_dir):
            pids.append(pid)
    return pids


def busy_reason(profile: Optional[str]) -> Optional[str]:
    claude_dir = claude_dir_for(profile)
    now_epoch = time.time()
    if any(_lock_is_fresh(path, now_epoch) for path in _lock_paths(claude_dir)):
        return BUSY_REFRESH_LOCK
    if live_claude_pids(claude_dir):
        return BUSY_CLAUDE_RUNNING
    return None

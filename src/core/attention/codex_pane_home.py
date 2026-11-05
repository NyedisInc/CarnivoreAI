
from __future__ import annotations

import os
import sqlite3
import subprocess
import threading
import time
from typing import Dict, Optional, Tuple

import structlog

from src.core.attention.codex_gather import DEFAULT_CODEX_HOME

logger = structlog.get_logger()

HOME_VARIABLE = "CODEX_HOME"

ANSWER_TTL_SECONDS = 30.0
UNREADABLE_TTL_SECONDS = 3.0
READ_TIMEOUT_SECONDS = 2.0

_LOCK = threading.Lock()
_CACHE: Dict[Tuple[str, str], Tuple[float, str]] = {}


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def _read_variable(socket: str, args: list) -> Optional[Tuple[Optional[str], bool]]:
    from src.core.account_switch.pane_account import parse_show_environment
    from src.core.tmux_control.reader import control_read
    from src.core.tmux_discovery import tmux_argv_prefix

    answered = control_read(socket, args)
    if answered is not None:
        profile = parse_show_environment(answered, 0, HOME_VARIABLE)
        return (profile.value, profile.inherited) if profile.readable else None
    try:
        done = subprocess.run(
            tmux_argv_prefix(socket) + args,
            stdin=subprocess.DEVNULL, capture_output=True, timeout=READ_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("codex_pane_home_read_failed", error=type(exc).__name__)
        return None
    if done.returncode == 1 and b"unknown variable" not in done.stderr:
        return None
    profile = parse_show_environment(done.stdout, done.returncode, HOME_VARIABLE)
    return (profile.value, profile.inherited) if profile.readable else None


def _recorded_home(socket: str, tmux_name: str) -> Optional[str]:
    import json
    from contextlib import closing

    from src.config import settings
    from src.config.provider_accounts import managed_dir_for
    from src.core.db import connect, db_path_for
    from src.core.provider_ledger.relay_accounts import CODEX_RELAY_NAME_RE

    try:
        db_path = db_path_for(settings.get_state_dir())
        if not db_path.exists():
            return None
        with closing(connect(db_path, create=False)) as conn:
            row = conn.execute(
                "SELECT launch_record FROM sessions WHERE tmux_name = ? AND tmux_socket = ? "
                "ORDER BY rowid DESC LIMIT 1", (tmux_name, socket)).fetchone()
        account_id = ((json.loads(row["launch_record"]).get("account") or {}).get("id")) if row and row["launch_record"] else None
    except (OSError, ValueError, TypeError, AttributeError, sqlite3.Error) as exc:
        logger.debug("codex_pane_home_record_unreadable", error=type(exc).__name__)
        return None
    if not isinstance(account_id, str) or not CODEX_RELAY_NAME_RE.fullmatch(account_id):
        return None
    home = managed_dir_for(account_id)
    return home if os.path.isdir(home) else None


def _measure(socket: str, tmux_name: str) -> Tuple[str, bool]:
    own = _read_variable(socket, ["show-environment", "-t", f"={tmux_name}", HOME_VARIABLE])
    if own is None:
        return DEFAULT_CODEX_HOME, False
    value, unset = own
    if unset:
        global_read = _read_variable(socket, ["show-environment", "-g", HOME_VARIABLE])
        if global_read is None:
            return DEFAULT_CODEX_HOME, False
        value = global_read[0]
    if not value or not os.path.isabs(os.path.expanduser(value)):
        return DEFAULT_CODEX_HOME, True
    return os.path.expanduser(value), True


def pane_codex_home(socket: Optional[str], tmux_name: Optional[str]) -> str:
    if not socket or not tmux_name:
        return DEFAULT_CODEX_HOME
    key = (str(socket), str(tmux_name))
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
    try:
        home, conclusive = _measure(*key)
        if not conclusive:
            recorded = _recorded_home(*key)
            if recorded:
                home, conclusive = recorded, True
    except Exception as exc:  # noqa: BLE001
        logger.debug("codex_pane_home_failed", error=type(exc).__name__)
        home, conclusive = DEFAULT_CODEX_HOME, False
    with _LOCK:
        if len(_CACHE) > 512:
            _CACHE.clear()
        _CACHE[key] = (now + (ANSWER_TTL_SECONDS if conclusive else UNREADABLE_TTL_SECONDS), home)
    return home

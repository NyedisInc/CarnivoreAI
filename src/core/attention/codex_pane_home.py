
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, Hashable, Mapping, Optional, Tuple, Union

import structlog

from src.core.attention.codex_gather import DEFAULT_CODEX_HOME

logger = structlog.get_logger()

HOME_VARIABLE = "CODEX_HOME"

ANSWER_TTL_SECONDS = 30.0
UNREADABLE_TTL_SECONDS = 3.0
READ_TIMEOUT_SECONDS = 2.0
GONE_TTL_SECONDS = 120.0
_SESSION_MISSING = (b"no such session", b"can't find session")

_LOCK = threading.Lock()
_CACHE: Dict[Tuple[str, str], Tuple[float, str]] = {}
_GONE: Dict[Tuple[str, str], Tuple[float, Hashable, str]] = {}


class _Gone:
    pass


_GONE_ANSWER = _Gone()


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()
        _GONE.clear()


def gone_identity(row: Mapping[str, Any]) -> Optional[Hashable]:
    epoch = row.get("tmux_created_epoch")
    if epoch is None:
        return None
    raw = row.get("launch_record")
    if raw in (None, ""):
        return (epoch, None)
    try:
        record = raw if isinstance(raw, dict) else json.loads(raw)
        account = (record.get("account") or {}).get("id")
    except (ValueError, TypeError, AttributeError):
        return None
    if account:
        return None
    return (epoch, raw if isinstance(raw, str) else json.dumps(raw, sort_keys=True, default=str))


def codex_home_for_row(
    family: Optional[str], socket: Optional[str], tmux_name: Optional[str], *, identity: Optional[Hashable] = None
) -> Optional[str]:
    from src.core.attention.evidence import FAMILY_CODEX

    if family != FAMILY_CODEX:
        return None
    return pane_codex_home(socket, tmux_name, identity=identity)


def _read_variable(socket: str, args: list) -> Union[Tuple[Optional[str], bool], _Gone, None]:
    from src.core.account_switch.pane_account import parse_show_environment
    from src.core.tmux_transport.run import tmux_run_sync

    done = tmux_run_sync(socket, *args, timeout=READ_TIMEOUT_SECONDS)
    if done.error:
        logger.debug("codex_pane_home_read_failed", error=done.error)
        return None
    returncode, stdout, stderr = done.returncode, done.stdout, done.stderr
    if returncode == 1 and b"unknown variable" not in stderr:
        return _GONE_ANSWER if any(words in stderr for words in _SESSION_MISSING) else None
    profile = parse_show_environment(stdout, returncode, HOME_VARIABLE)
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
    if not isinstance(account_id, str) or not account_id:
        return None
    home = managed_dir_for(account_id) if CODEX_RELAY_NAME_RE.fullmatch(account_id) else _local_account_home(account_id)
    return home if home and os.path.isdir(home) else None


def _local_account_home(account_id: str) -> Optional[str]:
    from src.core.account_switch import launch_env, session_pin
    from src.core.account_switch.active import find_account
    from src.core.provider_ledger.login_command import login_profile_dir

    try:
        account = find_account(session_pin.all_accounts(launch_env._config_path()), account_id, "codex")
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.debug("codex_pane_home_accounts_unreadable", error=type(exc).__name__)
        return None
    return os.path.expanduser(login_profile_dir(account)) if account is not None else None


def _measure(socket: str, tmux_name: str) -> Tuple[str, bool, bool]:
    own = _read_variable(socket, ["show-environment", "-t", f"={tmux_name}", HOME_VARIABLE])
    if own is _GONE_ANSWER:
        return DEFAULT_CODEX_HOME, False, True
    if own is None:
        return DEFAULT_CODEX_HOME, False, False
    value, unset = own
    if unset:
        global_read = _read_variable(socket, ["show-environment", "-g", HOME_VARIABLE])
        if global_read is None or global_read is _GONE_ANSWER:
            return DEFAULT_CODEX_HOME, False, False
        value = global_read[0]
    if not value or not os.path.isabs(os.path.expanduser(value)):
        return DEFAULT_CODEX_HOME, True, False
    return os.path.expanduser(value), True, False


def pane_codex_home(socket: Optional[str], tmux_name: Optional[str], *, identity: Optional[Hashable] = None) -> str:
    if not socket or not tmux_name:
        return DEFAULT_CODEX_HOME
    key = (str(socket), str(tmux_name))
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
        gone = _GONE.get(key) if identity is not None else None
        if gone is not None and gone[0] > now and gone[1] == identity:
            return gone[2]
    measured_conclusive = False
    session_gone = False
    try:
        home, measured_conclusive, session_gone = _measure(*key)
        conclusive = measured_conclusive
        if not conclusive:
            recorded = _recorded_home(*key)
            if recorded:
                home, conclusive = recorded, True
    except Exception as exc:  # noqa: BLE001
        logger.debug("codex_pane_home_failed", error=type(exc).__name__)
        home, conclusive, session_gone = DEFAULT_CODEX_HOME, False, False
    with _LOCK:
        if len(_CACHE) > 512:
            _CACHE.clear()
        _CACHE[key] = (now + (ANSWER_TTL_SECONDS if conclusive else UNREADABLE_TTL_SECONDS), home)
        if measured_conclusive:
            _GONE.pop(key, None)
        elif session_gone and not conclusive and identity is not None:
            if len(_GONE) > 512:
                _GONE.clear()
            _GONE[key] = (now + GONE_TTL_SECONDS, identity, home)
    return home

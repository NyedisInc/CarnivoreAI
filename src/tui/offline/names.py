
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import structlog

from src.core.safe_io.readonly_db import READONLY_TIMEOUT_QUICK_S, connect_readonly
from src.core.db_rename.legacy import readable_db_path
from src.core.product_identity import LEGACY_STATE_DIR_NAMES, STATE_DIR_NAME

logger = structlog.get_logger(__name__)

APP_SUPPORT = Path("~/Library/Application Support")

NAMES_SQL = (
    "SELECT s.tmux_name, s.tmux_created_epoch, s.tmux_socket, s.title, s.claude_title, p.display_name "
    "FROM sessions s LEFT JOIN projects p ON p.id = s.project_id "
    "WHERE s.host_key = 'local' AND s.tmux_name IN ({marks}) ORDER BY s.updated_at DESC"
)


@dataclass(frozen=True)
class SessionNames:

    display_name: Optional[str]
    project: Optional[str]


def offline_state_dir(override: Optional[str]) -> Optional[Path]:
    if override:
        path = Path(override).expanduser()
        return path if path.is_dir() else None
    for name in (STATE_DIR_NAME, *LEGACY_STATE_DIR_NAMES):
        path = APP_SUPPORT.expanduser() / name
        if path.is_dir():
            return path
    return None


def _text(value: object) -> Optional[str]:
    return value.strip() or None if isinstance(value, str) else None


def read_names(
    state_dir: Optional[Path], socket_name: str, sessions: Iterable[tuple[str, Optional[int]]]
) -> dict[str, SessionNames]:
    wanted = dict(sessions)
    if state_dir is None or not wanted:
        return {}
    path = readable_db_path(state_dir)
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return {}
    except OSError:
        return {}
    marks = ",".join("?" for _ in wanted)
    try:
        conn = connect_readonly(path, timeout=READONLY_TIMEOUT_QUICK_S)
        try:
            rows = conn.execute(NAMES_SQL.format(marks=marks), tuple(wanted)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as err:
        logger.warning("tui_offline_names_unreadable", error=type(err).__name__)
        return {}
    best: dict[str, tuple[int, SessionNames]] = {}
    for tmux_name, epoch, socket, title, claude_title, project in rows:
        rank = 2 if socket == socket_name and epoch is not None and epoch == wanted.get(tmux_name) else (
            1 if socket == socket_name else 0
        )
        names = SessionNames(_text(title) or _text(claude_title), _text(project))
        if tmux_name not in best or rank > best[tmux_name][0]:
            best[tmux_name] = (rank, names)
    return {name: names for name, (_rank, names) in best.items()}

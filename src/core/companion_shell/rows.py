
from __future__ import annotations

import re
import sqlite3
from typing import Dict

from src.core.companion_shell.ddl import COMPANION_OF_COLUMN
from src.core.db import column_exists
from src.core.session_label import label_from_tmux_name
from src.core.product_identity import LEGACY_TMUX_SESSION_PREFIXES, TMUX_SESSION_PREFIX

OPEN_SHELL_LABEL = "an open terminal shell"
_APP_PREFIXES = (TMUX_SESSION_PREFIX, *LEGACY_TMUX_SESSION_PREFIXES)
_HIDDEN_SHELL_NAME = re.compile("^(?:" + "|".join(re.escape(p) for p in _APP_PREFIXES) + r")sh-\d+$")


def exclude_clause(conn: sqlite3.Connection, alias: str = "") -> str:
    if not column_exists(conn, "sessions", COMPANION_OF_COLUMN):
        return ""
    prefix = f"{alias}." if alias else ""
    return f" AND {prefix}{COMPANION_OF_COLUMN} IS NULL"


def companion_labels(conn: sqlite3.Connection) -> Dict[str, str]:
    if not column_exists(conn, "sessions", COMPANION_OF_COLUMN):
        return {}
    sql = (f"SELECT s.tmux_name AS shell, a.title AS title, a.tmux_name AS parent_name "
           f"FROM sessions s LEFT JOIN sessions a ON a.id = s.{COMPANION_OF_COLUMN} "
           f"WHERE s.{COMPANION_OF_COLUMN} IS NOT NULL AND s.tmux_name IS NOT NULL")
    labels: Dict[str, str] = {}
    for r in conn.execute(sql):
        parent = (r["title"] or "").strip() or label_from_tmux_name(r["parent_name"])
        labels[r["shell"]] = f"the terminal shell of {parent}" if parent else OPEN_SHELL_LABEL
    return labels


def shell_label(name: str, labels: Dict[str, str]) -> str:
    if name in labels:
        return labels[name]
    return OPEN_SHELL_LABEL if _HIDDEN_SHELL_NAME.match(name) else name

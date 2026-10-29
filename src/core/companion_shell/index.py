
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional, Set

import structlog

from src.core.companion_shell.ddl import COMPANION_OF_COLUMN
from src.core.db import DatastoreError, column_exists, connect, db_path_for
from src.core.hosts.identity import REMOTE_ID_PREFIX

logger = structlog.get_logger()



class CompanionIndex:

    def __init__(self) -> None:
        self._shell_by_agent: Dict[int, int] = {}
        self._names: Dict[int, str] = {}
        self._name_set: Set[str] = set()
        self._reserved: Set[str] = set()
        self.loaded = False

    def load(self, conn: sqlite3.Connection) -> int:
        shells: Dict[int, int] = {}
        names: Dict[int, str] = {}
        if column_exists(conn, "sessions", COMPANION_OF_COLUMN):
            for row_id, agent_row, tmux_name in conn.execute(
                f"SELECT id, {COMPANION_OF_COLUMN}, tmux_name FROM sessions "
                f"WHERE {COMPANION_OF_COLUMN} IS NOT NULL"
            ):
                shells[int(agent_row)] = int(row_id)
                if tmux_name:
                    names[int(row_id)] = str(tmux_name)
        return self.apply(shells, names)

    def apply(self, shells: Dict[int, int], names: Dict[int, str]) -> int:
        self._shell_by_agent, self._names = dict(shells), dict(names)
        self._name_set = set(self._names.values())
        self.loaded = True
        logger.info("companion_index_loaded", companions=len(shells))
        return len(shells)

    def reserve(self, session_id: str) -> None:
        self._reserved.add(session_id)

    def release(self, session_id: str) -> None:
        self._reserved.discard(session_id)

    def link(self, *, agent_row: int, shell_row: int, tmux_name: Optional[str]) -> None:
        self._shell_by_agent[agent_row] = shell_row
        self._name_set.discard(self._names.pop(shell_row, None))
        if tmux_name:
            self._names[shell_row] = tmux_name
            self._name_set.add(tmux_name)

    def unlink(self, agent_row: int) -> None:
        shell_row = self._shell_by_agent.pop(agent_row, None)
        if shell_row is not None:
            self._name_set.discard(self._names.pop(shell_row, None))

    def tmux_names(self) -> Set[str]:
        return set(self._name_set)

    def shell_row_for(self, agent_row: int) -> Optional[int]:
        return self._shell_by_agent.get(agent_row)

    def is_hidden_name(self, tmux_name: Optional[str]) -> bool:
        return bool(tmux_name and tmux_name in self._name_set)

    def is_hidden_session(self, session: Any) -> bool:
        if session.id.startswith(REMOTE_ID_PREFIX):
            return False
        return session.id in self._reserved or self.is_hidden_name(getattr(session, "tmux_session", None))

    @staticmethod
    def is_companion_row(row: Any) -> bool:
        try:
            return row[COMPANION_OF_COLUMN] is not None
        except (KeyError, IndexError):
            return False


def install(registry: Any, state_dir: Path) -> CompanionIndex:
    index = CompanionIndex()
    try:
        with closing(connect(db_path_for(state_dir), create=False)) as conn:
            index.load(conn)
    except (DatastoreError, sqlite3.Error, OSError) as exc:
        logger.warning("companion_index_load_failed", error=type(exc).__name__)
    registry.hide_when(index.is_hidden_session)
    return index

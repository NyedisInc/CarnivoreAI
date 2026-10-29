
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import structlog

logger = structlog.get_logger()

FILE_NAME = "agent_actions.db"
SCHEMA_VERSION = 1

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS actions ("
    " id TEXT PRIMARY KEY, created_at REAL NOT NULL, status TEXT NOT NULL, decided_at REAL, body TEXT NOT NULL)"
)


class ApprovalsStoreError(RuntimeError):
    """The approvals file could not be opened, read or written; the message names the step."""


class ActionFile:

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._ensure()

    def _connect(self) -> sqlite3.Connection:
        try:
            return sqlite3.connect(str(self.path), isolation_level=None, timeout=10.0)
        except sqlite3.Error as exc:
            raise ApprovalsStoreError(f"open {self.path.name}: {exc}") from exc

    def _ensure(self) -> None:
        fresh = not self.path.exists()
        try:
            with closing(self._connect()) as conn:
                conn.execute(_SCHEMA)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except sqlite3.Error as exc:
            raise ApprovalsStoreError(f"create {self.path.name}: {exc}") from exc
        if fresh:
            os.chmod(self.path, 0o600)

    def save(self, row: Dict[str, Any]) -> None:
        body = json.dumps(row, default=str)
        try:
            with closing(self._connect()) as conn:
                conn.execute("INSERT OR REPLACE INTO actions VALUES (?, ?, ?, ?, ?)",
                             (row["id"], row["created_at"], row["status"], row.get("decided_at"), body))
        except sqlite3.Error as exc:
            raise ApprovalsStoreError(f"save {row['id']}: {exc}") from exc

    def delete(self, ids: Iterable[str]) -> None:
        ids = list(ids)
        if not ids:
            return
        try:
            with closing(self._connect()) as conn:
                conn.executemany("DELETE FROM actions WHERE id = ?", [(i,) for i in ids])
        except sqlite3.Error as exc:
            raise ApprovalsStoreError(f"delete: {exc}") from exc

    def load(self) -> List[Dict[str, Any]]:
        try:
            with closing(self._connect()) as conn:
                rows = conn.execute("SELECT id, body FROM actions ORDER BY created_at").fetchall()
        except sqlite3.Error as exc:
            raise ApprovalsStoreError(f"load: {exc}") from exc
        out: List[Dict[str, Any]] = []
        for action_id, body in rows:
            try:
                parsed = json.loads(body)
            except ValueError:
                logger.warning("agent_action_row_unreadable", id=action_id)
                continue
            if isinstance(parsed, dict):
                out.append(parsed)
        return out


def open_in(state_dir: Optional[Path]) -> Optional[ActionFile]:
    """The approvals file in ``state_dir``, or None when there is none or it cannot be opened (logged).

    Description: a broken file must never take the gate down: the store then runs in memory as before and the
      log says so. Inputs: state_dir (Path | None). Output: ActionFile | None.
    """
    if state_dir is None:
        return None
    try:
        return ActionFile(Path(state_dir) / FILE_NAME)
    except ApprovalsStoreError as exc:
        logger.error("agent_actions_file_unavailable", error=str(exc))
        return None

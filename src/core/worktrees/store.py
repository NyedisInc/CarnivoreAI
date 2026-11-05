from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import structlog

FILENAME = "worktrees.db"

_DDL = (
    "CREATE TABLE IF NOT EXISTS worktrees (path TEXT PRIMARY KEY, repo TEXT NOT NULL, branch TEXT NOT NULL,"
    " base_branch TEXT NOT NULL, created_at REAL NOT NULL, removed_at REAL)",
    "CREATE TABLE IF NOT EXISTS setup_approvals (repo TEXT NOT NULL, sha256 TEXT NOT NULL, approved_at REAL NOT NULL,"
    " PRIMARY KEY (repo, sha256))",
)


logger = structlog.get_logger()


@dataclass(frozen=True)
class WorktreeRecord:

    path: str
    repo: str
    branch: str
    base_branch: str
    created_at: float
    removed_at: Optional[float]


class WorktreeStore:

    def __init__(self, state_dir: Path) -> None:
        self._path = Path(state_dir) / FILENAME

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, timeout=5)
        conn.row_factory = sqlite3.Row
        for stmt in _DDL:
            conn.execute(stmt)
        return conn

    def record(self, path: str, repo: str, branch: str, base_branch: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO worktrees (path, repo, branch, base_branch, created_at, removed_at) VALUES (?,?,?,?,?,NULL)"
                " ON CONFLICT(path) DO UPDATE SET repo=excluded.repo, branch=excluded.branch,"
                " base_branch=excluded.base_branch, removed_at=NULL",
                (path, repo, branch, base_branch, time.time()))

    def get(self, path: str) -> Optional[WorktreeRecord]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM worktrees WHERE path = ? AND removed_at IS NULL", (path,)).fetchone()
        return WorktreeRecord(**dict(row)) if row else None

    def live(self) -> List[WorktreeRecord]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM worktrees WHERE removed_at IS NULL ORDER BY created_at").fetchall()
        return [WorktreeRecord(**dict(r)) for r in rows]

    def mark_removed(self, path: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE worktrees SET removed_at = ? WHERE path = ?", (time.time(), path))

    def repo_by_path(self) -> Dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return {r.path: r.repo for r in self.live()}
        except sqlite3.Error as exc:
            logger.warning("worktree_store_unreadable", path=str(self._path), error=str(exc))
            return {}

    def approve(self, repo: str, sha256: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("INSERT OR IGNORE INTO setup_approvals (repo, sha256, approved_at) VALUES (?,?,?)",
                         (repo, sha256, time.time()))

    def is_approved(self, repo: str, sha256: str) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT 1 FROM setup_approvals WHERE repo = ? AND sha256 = ?", (repo, sha256)).fetchone()
        return row is not None


def default_store() -> WorktreeStore:
    from src.config import settings

    return WorktreeStore(Path(os.fspath(settings.get_state_dir())))

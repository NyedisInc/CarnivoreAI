"""Saved versions of a local SKILL.md (issue #1925): a small SQLite under the state directory.

Not ``carnivore.db`` and not the skill folder. A version is the FULL bytes of one state of the file,
keyed by the real path of that SKILL.md AND the identity of its folder: a save stores the new text with
the note typed for it (and, first, the text it replaced when no version holds that yet), so a rollback
can itself be rolled back. Only the last :data:`KEEP_PER_SKILL` versions of one file are kept. A skill
removed and later recreated at the same path is a different folder, so it starts with no versions.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.test_write_guard import assert_test_write_allowed

DB_NAME = "skill_md_versions.db"
KEEP_PER_SKILL = 50
NOTE_MAX = 200
_SCHEMA = """
CREATE TABLE IF NOT EXISTS versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  skill_key TEXT NOT NULL,
  created_at REAL NOT NULL,
  note TEXT NOT NULL,
  action TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size INTEGER NOT NULL,
  redacted INTEGER NOT NULL DEFAULT 0,
  content BLOB NOT NULL,
  lines INTEGER NOT NULL DEFAULT 0,
  ident TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS versions_by_skill ON versions (skill_key, id);
"""


def skill_identity(key: str) -> str:
    try:
        info = os.stat(os.path.dirname(key))
    except OSError:
        return ""
    born = getattr(info, "st_birthtime_ns", None) or int(getattr(info, "st_birthtime", 0) * 1e9)
    return f"{info.st_dev}:{info.st_ino}:{born}"


class SkillMdVersionStore:

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect(self, write: bool) -> sqlite3.Connection:
        if not write and not self._path.exists():
            memory = sqlite3.connect(":memory:")
            memory.executescript(_SCHEMA)
            return memory
        assert_test_write_allowed(self._path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            os.close(os.open(str(self._path), os.O_CREAT | os.O_WRONLY, 0o600))
        conn = sqlite3.connect(str(self._path), timeout=5.0)
        conn.executescript(_SCHEMA)
        have = {row[1] for row in conn.execute("PRAGMA table_info(versions)")}
        for column, ddl in (("lines", "INTEGER NOT NULL DEFAULT 0"), ("ident", "TEXT NOT NULL DEFAULT ''")):
            if column not in have:
                with conn:
                    conn.execute(f"ALTER TABLE versions ADD COLUMN {column} {ddl}")
        return conn

    def add(self, key: str, created_at: float, note: str, action: str, sha256: str, content: bytes, redacted: bool = False) -> int:
        size = len(content)
        lines = len(content.splitlines())
        ident = skill_identity(key)
        if redacted:
            content = b""
        with closing(self._connect(True)) as conn, conn:
            conn.execute("DELETE FROM versions WHERE skill_key = ? AND ident != ?", (key, ident))
            cur = conn.execute(
                "INSERT INTO versions (skill_key, created_at, note, action, sha256, size, redacted, content, lines, ident) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (key, created_at, note[:NOTE_MAX], action, sha256, size, int(redacted), content, lines, ident),
            )
            conn.execute(
                "DELETE FROM versions WHERE skill_key = ? AND id NOT IN "
                "(SELECT id FROM versions WHERE skill_key = ? ORDER BY id DESC LIMIT ?)",
                (key, key, KEEP_PER_SKILL),
            )
            return int(cur.lastrowid)

    def latest_sha(self, key: str) -> Optional[str]:
        with closing(self._connect(False)) as conn:
            row = conn.execute(
                "SELECT sha256 FROM versions WHERE skill_key = ? AND ident = ? ORDER BY id DESC LIMIT 1", (key, skill_identity(key))
            ).fetchone()
        return None if row is None else row[0]

    def list(self, key: str) -> List[Dict[str, Any]]:
        with closing(self._connect(False)) as conn:
            rows = conn.execute(
                "SELECT id, created_at, note, sha256, size, action, redacted, lines FROM versions "
                "WHERE skill_key = ? AND ident = ? ORDER BY id DESC",
                (key, skill_identity(key)),
            ).fetchall()
        return [
            {
                "id": r[0], "created_at": r[1], "note": r[2], "sha256": r[3], "size": r[4], "lines": r[7],
                "action": r[5], "redacted": bool(r[6]),
            }
            for r in rows
        ]

    def get(self, key: str, version_id: int) -> Optional[Tuple[bytes, str, bool]]:
        with closing(self._connect(False)) as conn:
            row = conn.execute(
                "SELECT content, sha256, redacted FROM versions WHERE skill_key = ? AND ident = ? AND id = ?",
                (key, skill_identity(key), version_id),
            ).fetchone()
        return None if row is None else (bytes(row[0]), row[1], bool(row[2]))

    def delete(self, key: str, version_id: int) -> bool:
        with closing(self._connect(False)) as conn, conn:
            return conn.execute(
                "DELETE FROM versions WHERE skill_key = ? AND ident = ? AND id = ?", (key, skill_identity(key), version_id)
            ).rowcount > 0

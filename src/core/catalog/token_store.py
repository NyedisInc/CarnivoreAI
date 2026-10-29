
from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import structlog

from src.core.db import connect

logger = structlog.get_logger()

TOKEN_DB_FILENAME = "catalog_tokens.db"

_ROW_ID = 1

GUEST_PROVIDER = "guest"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_tokens (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    login TEXT NOT NULL,
    access_token TEXT NOT NULL,
    access_expires_at INTEGER NOT NULL,
    refresh_token TEXT NOT NULL,
    refresh_expires_at INTEGER NOT NULL
)
"""

_GUEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_guest (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    guest_id TEXT NOT NULL
)
"""


def token_db_path(state_dir: Path) -> Path:
    return Path(state_dir) / TOKEN_DB_FILENAME


@dataclass(frozen=True)
class CatalogSession:

    login: str
    access_token: str
    access_expires_at: int
    refresh_token: str
    refresh_expires_at: int
    provider: Optional[str] = None

    @property
    def is_guest(self) -> bool:
        return self.provider == GUEST_PROVIDER


class CatalogTokenStore:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.execute(_SCHEMA)
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(catalog_tokens)")}
        if "provider" not in columns:
            self._conn.execute("ALTER TABLE catalog_tokens ADD COLUMN provider TEXT")
        self._conn.execute(_GUEST_SCHEMA)

    def guest_id(self) -> Optional[str]:
        row = self._conn.execute("SELECT guest_id FROM catalog_guest WHERE id = ?", (_ROW_ID,)).fetchone()
        return str(row["guest_id"]) if row else None

    def set_guest_id(self, guest_id: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO catalog_guest (id, guest_id) VALUES (?, ?)", (_ROW_ID, guest_id))

    def clear_guest_id(self) -> None:
        self._conn.execute("DELETE FROM catalog_guest")

    def save(self, session: CatalogSession) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO catalog_tokens "
            "(id, login, access_token, access_expires_at, refresh_token, "
            "refresh_expires_at, provider) VALUES (?, ?, ?, ?, ?, ?, ?)",
            self._values(session),
        )
        logger.info("catalog_signin_stored", provider=session.provider)

    def save_guest(self, session: CatalogSession) -> bool:
        values = self._values(session)
        cursor = self._conn.execute(
            "INSERT OR REPLACE INTO catalog_tokens (id, login, access_token, access_expires_at, "
            "refresh_token, refresh_expires_at, provider) "
            "SELECT ?, ?, ?, ?, ?, ?, ? WHERE NOT EXISTS "
            "(SELECT 1 FROM catalog_tokens WHERE id = ? AND COALESCE(provider, '') != ?)",
            (*values, _ROW_ID, GUEST_PROVIDER),
        )
        stored = cursor.rowcount > 0
        cursor.close()
        return stored

    @staticmethod
    def _values(session: CatalogSession) -> tuple:
        return (
            _ROW_ID,
            session.login,
            session.access_token,
            int(session.access_expires_at),
            session.refresh_token,
            int(session.refresh_expires_at),
            session.provider,
        )

    def save_if_refresh_is(self, expected_refresh: str, session: CatalogSession) -> bool:
        values = self._values(session)
        cursor = self._conn.execute(
            "UPDATE catalog_tokens SET login = ?, access_token = ?, access_expires_at = ?, "
            "refresh_token = ?, refresh_expires_at = ?, provider = ? "
            "WHERE id = ? AND refresh_token = ?",
            (*values[1:], _ROW_ID, expected_refresh),
        )
        swapped = cursor.rowcount > 0
        cursor.close()
        if swapped:
            logger.info("catalog_signin_stored", provider=session.provider)
        return swapped

    def read(self) -> Optional[CatalogSession]:
        cursor = self._conn.execute(
            "SELECT login, access_token, access_expires_at, refresh_token, "
            "refresh_expires_at, provider FROM catalog_tokens WHERE id = ?",
            (_ROW_ID,),
        )
        row = cursor.fetchone()
        cursor.close()
        if row is None:
            return None
        return CatalogSession(
            login=str(row["login"]),
            access_token=str(row["access_token"]),
            access_expires_at=int(row["access_expires_at"]),
            refresh_token=str(row["refresh_token"]),
            refresh_expires_at=int(row["refresh_expires_at"]),
            provider=str(row["provider"]) if row["provider"] else None,
        )

    def clear(self) -> bool:
        cursor = self._conn.execute("DELETE FROM catalog_tokens")
        removed = cursor.rowcount > 0
        cursor.close()
        self._conn.execute("VACUUM")
        logger.info("catalog_signin_cleared")
        return removed

    def clear_if_access_is(self, expected_access: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM catalog_tokens WHERE id = ? AND access_token = ?", (_ROW_ID, expected_access)
        )
        removed = cursor.rowcount > 0
        cursor.close()
        if removed:
            self._conn.execute("VACUUM")
            logger.info("catalog_signin_cleared")
        return removed

    def clear_if_refresh_is(self, expected_refresh: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM catalog_tokens WHERE id = ? AND refresh_token = ?",
            (_ROW_ID, expected_refresh),
        )
        removed = cursor.rowcount > 0
        cursor.close()
        if removed:
            self._conn.execute("VACUUM")
            logger.info("catalog_signin_cleared")
        return removed


@contextlib.contextmanager
def open_token_store(state_dir: Path) -> Iterator[CatalogTokenStore]:
    path = token_db_path(state_dir)
    with contextlib.closing(connect(path)) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
        store = CatalogTokenStore(conn)
        try:
            path.chmod(0o600)
        except OSError as exc:
            logger.warning(
                "catalog_token_store_chmod_failed", db=str(path), error=str(exc)
            )
        yield store

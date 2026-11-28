
from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import structlog

from src.core.db import connect


class TokenStoreError(ValueError):
    pass


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


_CLIENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_clients (
    client_key TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    login TEXT NOT NULL,
    provider TEXT,
    access_token TEXT,
    access_expires_at INTEGER,
    refresh_token TEXT,
    refresh_expires_at INTEGER,
    created_at INTEGER NOT NULL
)
"""

_FLAG_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_flags (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

MODE_BOUND = "bound"
MODE_OWN = "own"


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


@dataclass(frozen=True)
class ClientEntry:

    client_key: str
    mode: str
    login: str
    provider: Optional[str] = None
    access_token: Optional[str] = None
    access_expires_at: int = 0
    refresh_token: Optional[str] = None
    refresh_expires_at: int = 0

    def as_session(self) -> CatalogSession:
        if self.mode != MODE_OWN or not self.access_token or not self.refresh_token:
            raise TokenStoreError("a bound client holds no session of its own")
        return CatalogSession(self.login, self.access_token, self.access_expires_at, self.refresh_token,
                              self.refresh_expires_at, self.provider)


class CatalogTokenStore:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.execute(_SCHEMA)
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(catalog_tokens)")}
        if "provider" not in columns:
            self._conn.execute("ALTER TABLE catalog_tokens ADD COLUMN provider TEXT")
        self._conn.execute(_GUEST_SCHEMA)
        self._conn.execute(_CLIENT_SCHEMA)
        self._conn.execute(_FLAG_SCHEMA)


    def flag_get(self, name: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM catalog_flags WHERE name = ?", (name,)).fetchone()
        return str(row["value"]) if row else None

    def flag_set(self, name: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO catalog_flags (name, value) VALUES (?, ?)", (name, value))

    def flag_clear(self, name: str) -> None:
        self._conn.execute("DELETE FROM catalog_flags WHERE name = ?", (name,))

    @staticmethod
    def _client_of(row: sqlite3.Row) -> ClientEntry:
        return ClientEntry(
            client_key=str(row["client_key"]), mode=str(row["mode"]), login=str(row["login"]),
            provider=str(row["provider"]) if row["provider"] else None,
            access_token=row["access_token"], access_expires_at=int(row["access_expires_at"] or 0),
            refresh_token=row["refresh_token"], refresh_expires_at=int(row["refresh_expires_at"] or 0),
        )

    def client_get(self, client_key: str) -> Optional[ClientEntry]:
        row = self._conn.execute("SELECT * FROM catalog_clients WHERE client_key = ?", (client_key,)).fetchone()
        return self._client_of(row) if row else None

    def clients_all(self) -> list:
        return [self._client_of(r) for r in self._conn.execute("SELECT * FROM catalog_clients")]

    def client_put(self, entry: ClientEntry, now: int) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO catalog_clients (client_key, mode, login, provider, access_token, "
            "access_expires_at, refresh_token, refresh_expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (entry.client_key, entry.mode, entry.login, entry.provider, entry.access_token,
             entry.access_expires_at, entry.refresh_token, entry.refresh_expires_at, now),
        )
        logger.info("catalog_client_stored", mode=entry.mode)

    def client_save_if_refresh_is(self, client_key: str, expected_refresh: str, session: CatalogSession) -> bool:
        cursor = self._conn.execute(
            "UPDATE catalog_clients SET login = ?, access_token = ?, access_expires_at = ?, refresh_token = ?, "
            "refresh_expires_at = ?, provider = ? WHERE client_key = ? AND mode = ? AND refresh_token = ?",
            (session.login, session.access_token, int(session.access_expires_at), session.refresh_token,
             int(session.refresh_expires_at), session.provider, client_key, MODE_OWN, expected_refresh),
        )
        swapped = cursor.rowcount > 0
        cursor.close()
        return swapped

    def client_delete(self, client_key: str) -> bool:
        cursor = self._conn.execute("DELETE FROM catalog_clients WHERE client_key = ?", (client_key,))
        removed = cursor.rowcount > 0
        cursor.close()
        if removed:
            self._conn.execute("VACUUM")
            logger.info("catalog_client_cleared")
        return removed

    def clients_clear(self, bound_only: bool = False) -> list:
        gone = [e for e in self.clients_all() if not bound_only or e.mode == MODE_BOUND]
        for entry in gone:
            self._conn.execute("DELETE FROM catalog_clients WHERE client_key = ?", (entry.client_key,))
        if gone:
            self._conn.execute("VACUUM")
            logger.info("catalog_clients_cleared", count=len(gone))
        return gone

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


from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import stat
import threading
import time
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Callable, Optional, Union

import structlog

logger = structlog.get_logger()

PREFIX = "cak_"
DB_NAME = "api_keys.db"
NAME_MAX = 60
MAX_ACTIVE = 50
USED_FLUSH_SECONDS = 60.0
DISPLAY_CHARS = 6

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  display_prefix TEXT NOT NULL,
  created_at REAL NOT NULL,
  last_used_at REAL,
  revoked_at REAL
);
"""
_PUBLIC_COLUMNS = ("id", "name", "display_prefix", "created_at", "last_used_at", "revoked_at")


class ApiKeyError(ValueError):
    pass


class ApiKeyStoreError(OSError):
    """The key file is unsafe (a symlink, not a regular file) and was refused."""


def is_api_key(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(PREFIX)


def hash_key(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _clean_name(name: str) -> str:
    cleaned = unicodedata.normalize("NFC", str(name or "")).strip()
    if not cleaned:
        raise ApiKeyError("a key needs a name")
    if len(cleaned) > NAME_MAX:
        raise ApiKeyError(f"a key name is at most {NAME_MAX} characters")
    if any(unicodedata.category(ch).startswith("C") for ch in cleaned):
        raise ApiKeyError("a key name cannot hold control characters")
    return cleaned


def _row(cursor_row: sqlite3.Row) -> dict:
    return {k: cursor_row[k] for k in _PUBLIC_COLUMNS}


class ApiKeyStore:

    def __init__(self, path: Union[Path, Callable[[], Path]], clock: Callable[[], float] = time.time) -> None:
        self._path_of = path if callable(path) else (lambda: Path(path))
        self._clock = clock
        self._lock = threading.Lock()

    def _ensure_file(self, path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise ApiKeyStoreError(f"the api key file could not be opened safely: {type(exc).__name__}") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ApiKeyStoreError("the api key file is not a regular file")
            if stat.S_IMODE(info.st_mode) != 0o600:
                os.fchmod(fd, 0o600)
        finally:
            os.close(fd)

    def _connect(self) -> sqlite3.Connection:
        path = Path(self._path_of())
        self._ensure_file(path)
        conn = sqlite3.connect(path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        return conn

    def create(self, name: str) -> tuple[dict, str]:
        cleaned = _clean_name(name)
        secret = PREFIX + secrets.token_urlsafe(32)
        key_id = "key_" + secrets.token_hex(6)
        display = secret[: len(PREFIX) + DISPLAY_CHARS]
        now = self._clock()
        with self._lock, closing(self._connect()) as conn, conn:
            live = conn.execute("SELECT COUNT(*) FROM api_keys WHERE revoked_at IS NULL").fetchone()[0]
            if live >= MAX_ACTIVE:
                raise ApiKeyError(f"at most {MAX_ACTIVE} keys may be live; revoke one first")
            conn.execute(
                "INSERT INTO api_keys (id, name, key_hash, display_prefix, created_at) VALUES (?,?,?,?,?)",
                (key_id, cleaned, hash_key(secret), display, now),
            )
            row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        logger.info("api_key_created", key_id=key_id)
        return _row(row), secret

    def list(self) -> list[dict]:
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC, id").fetchall()
        return [_row(r) for r in rows]

    def revoke(self, key_id: str) -> Optional[dict]:
        with self._lock, closing(self._connect()) as conn, conn:
            conn.execute("UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (self._clock(), key_id))
            row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        if row is None:
            return None
        logger.info("api_key_revoked", key_id=key_id)
        return _row(row)

    def authenticate(self, secret: str) -> Optional[dict]:
        if not is_api_key(secret):
            return None
        wanted = hash_key(secret)
        now = self._clock()
        with self._lock, closing(self._connect()) as conn, conn:
            row = conn.execute("SELECT * FROM api_keys WHERE key_hash = ?", (wanted,)).fetchone()
            if row is None or not hmac.compare_digest(row["key_hash"], wanted):
                logger.warning("api_key_refused", reason="unknown")
                return None
            if row["revoked_at"] is not None:
                logger.warning("api_key_refused", reason="revoked", key_id=row["id"])
                return None
            last = row["last_used_at"]
            if last is None or now - last >= USED_FLUSH_SECONDS:
                conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, row["id"]))
                row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (row["id"],)).fetchone()
        return _row(row)


_stores: dict[str, ApiKeyStore] = {}
_stores_lock = threading.Lock()


def get_store() -> ApiKeyStore:
    from src.config import settings

    path = Path(settings.get_state_dir()) / DB_NAME
    with _stores_lock:
        store = _stores.get(str(path))
        if store is None:
            store = _stores[str(path)] = ApiKeyStore(path)
        return store


from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Set

import structlog

from src.core.deepsearch import constants as K
from src.core.deepsearch.cache import ddl

logger = structlog.get_logger()

_checked: Set[str] = set()
_check_lock = threading.Lock()
MAIN_SCHEMA: str = "cx"


def cache_path(state_dir: Path) -> Path:
    return Path(state_dir) / K.CACHE_FILENAME


def remove_files(path: Path) -> None:
    _checked.discard(str(path))
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def _healthy(path: Path) -> Optional[bool]:
    try:
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            return version in (0, K.CACHE_VERSION) and conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        logger.warning("deepsearch_cache_check_deferred", path=str(path), error=str(exc)[:200])
        return None
    except sqlite3.DatabaseError:
        return False


def ensure_checked(path: Path) -> None:
    key = str(path)
    if key in _checked:
        return
    with _check_lock:
        if key in _checked:
            return
        if path.exists():
            verdict = _healthy(path)
            if verdict is None:
                return
            if not verdict:
                logger.warning("deepsearch_cache_reset", path=key)
                remove_files(path)
        _checked.add(key)


def warm_in_background(state_dir: Path) -> threading.Thread:
    thread = threading.Thread(target=ensure_checked, args=(cache_path(state_dir),), name="deepsearch-cache-check", daemon=True)
    thread.start()
    return thread


def open_cache(state_dir: Path) -> sqlite3.Connection:
    path = cache_path(state_dir)
    ensure_checked(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
        conn.execute("BEGIN IMMEDIATE")
        for statement in ddl.statements():
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {K.CACHE_VERSION}")
        conn.execute("COMMIT")
    return conn


def attach_cache(conn: sqlite3.Connection, state_dir: Path) -> None:
    open_cache(state_dir).close()
    conn.execute(f"ATTACH DATABASE ? AS {K.CACHE_SCHEMA}", (str(cache_path(state_dir)),))


@contextmanager
def attached(conn: sqlite3.Connection, state_dir: Path) -> Iterator[sqlite3.Connection]:
    attach_cache(conn, state_dir)
    try:
        yield conn
    finally:
        detach_cache(conn)


def detach_cache(conn: sqlite3.Connection) -> None:
    conn.execute(f"DETACH DATABASE {K.CACHE_SCHEMA}")


def reader(state_dir: Path) -> sqlite3.Connection:
    from src.core.db import db_path_for

    conn = open_cache(state_dir)
    conn.execute(f"ATTACH DATABASE ? AS {MAIN_SCHEMA}", (str(db_path_for(state_dir)),))
    conn.row_factory = sqlite3.Row
    return conn

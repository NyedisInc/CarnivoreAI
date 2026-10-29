
from __future__ import annotations

import sqlite3
import uuid as _uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

import structlog

from src.core import product_identity
from src.core.db_reuse.executor import Executor
from src.core.db_rename.legacy import legacy_fallback_for
from src.core.hosts.table_columns import table_columns
from src.core.db_models import META_INSTALL_ID, META_SCHEMA_VERSION
from src.core.message_body_codec import register_body_functions

logger = structlog.get_logger()

DB_FILENAME = product_identity.DB_FILENAME

CONNECTION_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=30000",
    "PRAGMA journal_size_limit=67108864",
)


class DatastoreError(RuntimeError):
    pass


class DatastoreUnreadableError(DatastoreError):

    def __init__(self, message: str, path: Optional[Path] = None) -> None:
        super().__init__(message)
        self.path = path


def db_path_for(state_dir: Path) -> Path:
    fallback = legacy_fallback_for(Path(state_dir))
    return fallback if fallback is not None else Path(state_dir) / DB_FILENAME


def connect(path: Path, *, create: bool = True) -> sqlite3.Connection:
    path = Path(path)
    if not create and not path.exists():
        raise DatastoreUnreadableError(
            f"{path.name} does not exist at {path}", path
        )
    try:
        conn = sqlite3.connect(str(path), isolation_level=None, timeout=30.0)
    except sqlite3.Error as exc:
        raise DatastoreUnreadableError(
            f"could not open {path.name}: {exc}", path
        ) from exc
    conn.row_factory = sqlite3.Row
    try:
        for pragma in CONNECTION_PRAGMAS:
            conn.execute(pragma)
    except sqlite3.Error as exc:
        conn.close()
        raise DatastoreUnreadableError(
            f"could not apply pragmas to {path.name}: {exc}", path
        ) from exc
    try:
        register_body_functions(conn)
    except sqlite3.Error as exc:
        conn.close()
        raise DatastoreUnreadableError(
            f"could not register the body codec functions on {path.name}: "
            f"{exc}",
            path,
        ) from exc
    return conn


def integrity_check(conn: sqlite3.Connection) -> str:
    try:
        rows = conn.execute("PRAGMA main.integrity_check").fetchall()
    except sqlite3.Error as exc:
        return f"could not run integrity_check: {exc}"
    return "\n".join(str(row[0]) for row in rows) if rows else "no result"



_AFTER_COMMIT: Dict[int, List[Callable[[], None]]] = {}


def after_commit(conn: sqlite3.Connection, callback: Callable[[], None]) -> None:
    queued = _AFTER_COMMIT.get(id(conn))
    if queued is None:
        callback()
    else:
        queued.append(callback)


def _run_after_commit(callbacks: List[Callable[[], None]]) -> None:
    for callback in callbacks:
        try:
            callback()
        except Exception:  # noqa: BLE001
            logger.exception("db_after_commit_failed")


@contextmanager
def transaction(conn: Executor) -> Iterator[Executor]:
    conn.execute("BEGIN IMMEDIATE")
    queued: List[Callable[[], None]] = _AFTER_COMMIT.setdefault(id(conn), [])
    try:
        yield conn
    except BaseException:
        _AFTER_COMMIT.pop(id(conn), None)
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error as exc:
            logger.error("db_rollback_failed", error=str(exc))
        raise
    try:
        conn.execute("COMMIT")
    finally:
        _AFTER_COMMIT.pop(id(conn), None)
    _run_after_commit(queued)


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM main.sqlite_master WHERE type IN ('table','view') AND name = ?",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = table_columns(conn, table)
    return column in cols if cols else False


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    if not table_exists(conn, "meta"):
        return None
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return None if row is None else str(row[0])


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


SCHEMA_VERSION_ABSENT = "absent"

SCHEMA_VERSION_PARSED = "parsed"

SCHEMA_VERSION_UNREADABLE = "unreadable"


@dataclass(frozen=True)
class SchemaVersionRead:

    outcome: str
    value: Optional[int] = None
    raw: Optional[str] = None

    @property
    def readable(self) -> bool:
        return self.outcome != SCHEMA_VERSION_UNREADABLE


def read_schema_version(conn: sqlite3.Connection) -> SchemaVersionRead:
    raw = get_meta(conn, META_SCHEMA_VERSION)
    if raw is None:
        return SchemaVersionRead(SCHEMA_VERSION_ABSENT)
    try:
        return SchemaVersionRead(SCHEMA_VERSION_PARSED, value=int(str(raw).strip()), raw=str(raw))
    except (TypeError, ValueError):
        logger.warning("db_schema_version_unparseable", raw=raw)
        return SchemaVersionRead(SCHEMA_VERSION_UNREADABLE, raw=str(raw))


def get_schema_version(conn: sqlite3.Connection) -> int:
    read = read_schema_version(conn)
    return read.value if read.value is not None else 0


def database_is_populated(conn: sqlite3.Connection) -> Optional[bool]:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
        ).fetchone()
        if row is None:
            return False
        count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()
        if count is None:
            return None
        return int(count[0]) > 0
    except sqlite3.Error as exc:
        logger.warning("db_populated_probe_failed", error=str(exc))
        return None


def ensure_install_id(conn: sqlite3.Connection) -> str:
    existing = get_meta(conn, META_INSTALL_ID)
    if existing:
        return existing
    minted = str(_uuid.uuid4())
    set_meta(conn, META_INSTALL_ID, minted)
    return minted

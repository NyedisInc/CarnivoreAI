
from __future__ import annotations

import sqlite3
import uuid as _uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import structlog

from src.core import product_identity
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
    """cloude.db could not be opened, or failed PRAGMA integrity_check.
    """

    def __init__(self, message: str, path: Optional[Path] = None) -> None:
        super().__init__(message)
        self.path = path


def db_path_for(state_dir: Path) -> Path:
    """Return the app's SQLite database path inside a state directory.
    """
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



@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block inside one BEGIN IMMEDIATE ... COMMIT, rolling back on error.

    Description: BEGIN IMMEDIATE (not deferred) takes the write lock up
      front, so a migration cannot get half way through reading and then
      fail to upgrade its lock. Any exception rolls the whole block back
      and re-raises, which is what makes a half-applied migration leave
      meta.schema_version untouched.
    Inputs: conn (sqlite3.Connection) - opened by :func:`connect`, i.e.
      with isolation_level=None so this is the only transaction control.
    Output: yields the same connection.
    Raises: whatever the body raised, after ROLLBACK.
    Example:
        with transaction(conn):
            conn.execute("ALTER TABLE t ADD COLUMN a TEXT")
            conn.execute("ALTER TABLE t ADD COLUMN b TEXT")
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error as exc:
            logger.error("db_rollback_failed", error=str(exc))
        raise
    conn.execute("COMMIT")


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """Report whether a table exists, for idempotent migration steps.

    Description: every migration step inspects sqlite_master before it
      acts, so re-running a step after an interrupted attempt finishes
      the remaining work or no-ops rather than erroring.
    Inputs: conn (sqlite3.Connection), name (str) - table name.
    Output: bool - False when the name is absent or sqlite could not look.
    """
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
    """Read one meta value.

    Inputs: conn (sqlite3.Connection), key (str).
    Output: str | None - None when the key is absent OR the meta table
      does not exist yet (a pre-v1 database).
    """
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

# could not
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
    """Read meta.schema_version as an int, reporting 0 when there is none.

    Description: the REPORTING face of :func:`read_schema_version`, for
      call sites that only render or compare a number and take no
      irreversible action on it.

      DO NOT USE THIS AS A GATE. It collapses two different facts onto
      0: "no version recorded" and "a version that will not parse". That
      collapse is what let a populated 9-project database migrate with
      ZERO backups taken and be recorded in the trail as a bootstrap
      from 0. Anything deciding whether to back up, whether to migrate,
      or whether a file is a fresh install must call
      :func:`read_schema_version` and handle ``SCHEMA_VERSION_UNREADABLE``
      as its own outcome.
    Inputs: conn (sqlite3.Connection).
    Output: int - the parsed version, or 0 for both absent and
      unparseable. The caller cannot distinguish those two, which is
      precisely why this must not gate anything.
    """
    read = read_schema_version(conn)
    return read.value if read.value is not None else 0


def database_is_populated(conn: sqlite3.Connection) -> Optional[bool]:
    """Report whether this file already holds user data, or say it cannot tell.

    Description: a cheap independent discriminator against the
      fresh-install path, used when the recorded schema version cannot be
      trusted. The ``projects`` table is the right probe: it exists from
      v1 onward and an install with rows in it is by definition not a new
      file, whatever ``meta.schema_version`` happens to say.

      Three outcomes, because guessing here decides whether a real user's
      data gets backed up. A missing table is a genuine False (a file
      with no projects table has no projects). A query that FAILS is
      None - could not evaluate - and the caller must treat that with the
      same caution as True, never as a licence to skip the backup.
    Inputs: conn (sqlite3.Connection).
    Output: bool | None - True when at least one project row exists,
      False when the table exists and is empty or does not exist at all,
      None when the question could not be answered.
    Example:
        >>> database_is_populated(conn)  # doctest: +SKIP
        True
    """
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

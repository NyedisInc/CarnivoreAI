
from __future__ import annotations

import re
import sqlite3
from typing import Any, Callable, Optional

READ_KEYWORDS = frozenset({"SELECT", "EXPLAIN"})

READ_PRAGMAS = frozenset({"table_info", "schema_version", "database_list", "data_version", "index_list"})

_PRAGMA = re.compile(r'\s*PRAGMA\s+(?:(?:"[^"]*"|\w+)\s*\.\s*)?(\w+)\s*(.*)', re.IGNORECASE | re.DOTALL)


def _is_read_pragma(sql: str) -> bool:
    found = _PRAGMA.match(sql)
    if found is None:
        return False
    name, rest = found.group(1).lower(), found.group(2).strip().rstrip(";").strip()
    if name == "user_version":
        return not rest
    return name in READ_PRAGMAS


class DatastoreNotWritable(sqlite3.OperationalError):
    pass


class LazyWriteConnection:

    def __init__(self, read_conn: sqlite3.Connection, open_writer: Callable[[], Optional[sqlite3.Connection]], owns_read: bool = False) -> None:
        self._read = read_conn
        self._owns_read = owns_read
        self._open_writer = open_writer
        self._writer: Optional[sqlite3.Connection] = None

    @property
    def writer_opened(self) -> bool:
        return self._writer is not None

    @property
    def in_transaction(self) -> bool:
        return (self._writer or self._read).in_transaction

    def _writer_conn(self) -> sqlite3.Connection:
        if self._writer is None:
            self._writer = self._open_writer()
            if self._writer is None:
                raise DatastoreNotWritable("datastore not available for writing")
        return self._writer

    def _target(self, sql: str) -> sqlite3.Connection:
        if self._writer is not None and self._writer.in_transaction:
            return self._writer
        words = sql.lstrip().split(None, 1)
        first = words[0].upper() if words else ""
        if first in READ_KEYWORDS or (first == "PRAGMA" and _is_read_pragma(sql)):
            return self._read
        return self._writer_conn()

    def execute(self, sql: str, params: Any = ()) -> sqlite3.Cursor:
        return self._target(sql).execute(sql, params)

    def executemany(self, sql: str, rows: Any) -> sqlite3.Cursor:
        return self._writer_conn().executemany(sql, rows)

    def executescript(self, script: str) -> sqlite3.Cursor:
        return self._writer_conn().executescript(script)

    def cursor(self) -> sqlite3.Cursor:
        return self._writer_conn().cursor()

    def rollback(self) -> None:
        if self._writer is not None:
            self._writer.rollback()

    def __enter__(self) -> "LazyWriteConnection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if self._writer is not None:
            self._writer.__exit__(exc_type, exc, tb)
        return False

    def commit(self) -> None:
        if self._writer is not None:
            self._writer.commit()

    def close(self) -> None:
        writer, self._writer = self._writer, None
        try:
            if writer is not None:
                writer.close()
        finally:
            if self._owns_read:
                self._owns_read = False
                self._read.close()


def lazy_datastore(manager: Any) -> Optional[LazyWriteConnection]:
    read, owned = manager._name_read_connection()
    if read is None:
        return None
    return LazyWriteConnection(read, manager._writable_datastore_connection, owns_read=owned)

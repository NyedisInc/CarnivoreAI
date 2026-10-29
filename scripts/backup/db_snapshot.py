
from __future__ import annotations

import hashlib
import os
import sqlite3
from src.core.safe_io.readonly_db import connect_readonly
import struct
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

import structlog

from scripts.backup.errors import CopyFailed
from scripts.backup.targets import PRIVATE_FILE_MODE

logger = structlog.get_logger()

_FETCH_ROWS = 5000
_TAG_NULL, _TAG_INT, _TAG_REAL, _TAG_TEXT, _TAG_BLOB = b"N", b"I", b"R", b"T", b"B"


def open_readonly(path: Path) -> sqlite3.Connection:
    try:
        return connect_readonly(path)
    except sqlite3.Error as exc:
        raise CopyFailed(f"cannot open {path} read-only: {exc}") from exc


def _put(digest: Any, value: object) -> None:
    if value is None:
        digest.update(_TAG_NULL)
        return
    if isinstance(value, int):
        payload, tag = str(value).encode(), _TAG_INT
    elif isinstance(value, float):
        payload, tag = struct.pack(">d", value), _TAG_REAL
    elif isinstance(value, str):
        payload, tag = value.encode("utf-8", "surrogatepass"), _TAG_TEXT
    else:
        payload, tag = bytes(value), _TAG_BLOB
    digest.update(tag + struct.pack(">Q", len(payload)) + payload)


def _order_by(conn: sqlite3.Connection, table: str) -> str:
    try:
        conn.execute(f'SELECT rowid FROM "{table}" LIMIT 0')
        return "rowid"
    except sqlite3.OperationalError:
        pass
    keys = [r[1] for r in sorted(conn.execute(f'PRAGMA table_info("{table}")'), key=lambda r: r[5]) if r[5] > 0]
    return ", ".join(f'"{k}"' for k in keys) or "1"


def table_digest(conn: sqlite3.Connection, table: str) -> Dict[str, Any]:
    digest, rows = hashlib.sha256(), 0
    cursor = conn.execute(f'SELECT * FROM "{table}" ORDER BY {_order_by(conn, table)}')
    while True:
        batch = cursor.fetchmany(_FETCH_ROWS)
        if not batch:
            break
        for row in batch:
            for value in row:
                _put(digest, value)
            digest.update(b"\n")
            rows += 1
    return {"rows": rows, "sha256": digest.hexdigest()}


def snapshot_tables(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    conn.execute("BEGIN")
    try:
        for name, sql in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
            out[name] = {"virtual": True} if (sql or "").upper().startswith("CREATE VIRTUAL") else table_digest(conn, name)
    finally:
        conn.rollback()
    return out


def database_facts(conn: sqlite3.Connection) -> Dict[str, Any]:
    schema: Optional[str] = None
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        schema = None if row is None else str(row[0])
    except sqlite3.OperationalError:
        pass
    return {"user_version": int(conn.execute("PRAGMA user_version").fetchone()[0]), "schema_version": schema}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe_database(path: Path, *, check_integrity: bool) -> Dict[str, Any]:
    try:
        with closing(open_readonly(path)) as conn:
            facts = database_facts(conn)
            verdict = str(conn.execute("PRAGMA integrity_check").fetchone()[0]) if check_integrity else "not checked"
            return {**facts, "integrity": verdict, "tables": snapshot_tables(conn)}
    except sqlite3.Error as exc:
        raise CopyFailed(f"cannot read {path}: {exc}") from exc


def _set_aside(path: Path) -> None:
    if path.exists():
        path.rename(path.with_name(path.name + ".failed"))


def copy_database(source: Path, dest: Path) -> Dict[str, Any]:
    if dest.exists():
        raise CopyFailed(f"{dest} already exists")
    try:
        with closing(open_readonly(source)) as src, closing(sqlite3.connect(str(dest))) as out:
            src.backup(out)
            out.execute("PRAGMA journal_mode=DELETE")
        os.chmod(dest, PRIVATE_FILE_MODE)
        with dest.open("rb") as handle:
            os.fsync(handle.fileno())
        described = describe_database(dest, check_integrity=True)
        if described["integrity"] != "ok":
            raise CopyFailed(f"the copy of {source.name} failed its integrity check: {described['integrity'][:120]}")
    except CopyFailed:
        _set_aside(dest)
        raise
    except (sqlite3.Error, OSError) as exc:
        _set_aside(dest)
        raise CopyFailed(f"copy of {source} failed: {exc}") from exc
    logger.info("phase_backup_db_copied", db=source.name, tables=len(described["tables"]))
    return {**described, "bytes": dest.stat().st_size, "file_sha256": file_sha256(dest)}


class TableDiff(NamedTuple):

    table: str
    message: str


def diff_tables(expected: Dict[str, Dict[str, Any]], actual: Dict[str, Dict[str, Any]]) -> List[TableDiff]:
    problems: List[TableDiff] = []
    for name in sorted(set(expected) | set(actual)):
        want, got = expected.get(name), actual.get(name)
        if want is None:
            problems.append(TableDiff(name, "new table"))
        elif got is None:
            problems.append(TableDiff(name, "table is gone"))
        elif want.get("virtual") or got.get("virtual"):
            continue
        elif want["sha256"] != got["sha256"]:
            problems.append(TableDiff(name, f"{want['rows']} rows -> {got['rows']} rows, content changed"))
    return problems



from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import structlog

from src.core.safe_io.readonly_db import connect_readonly
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()


class BackupFailed(Exception):
    pass


def _counts(conn: sqlite3.Connection) -> Dict[str, int]:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {name: int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]) for name in names}


def verify(copy: Path, *, expect_version: int, expect_counts: Dict[str, int]) -> None:
    try:
        with closing(connect_readonly(copy)) as check:
            verdict = check.execute("PRAGMA integrity_check").fetchone()[0]
            version = int(check.execute("PRAGMA user_version").fetchone()[0])
            counts = _counts(check)
    except sqlite3.Error as exc:
        raise BackupFailed(f"the backup could not be opened read-only: {exc}") from exc
    if verdict != "ok":
        raise BackupFailed(f"the backup failed its integrity check: {str(verdict)[:120]}")
    if version != expect_version:
        raise BackupFailed(f"the backup is schema {version}, expected {expect_version}")
    if counts != expect_counts:
        differ = sorted(t for t in set(counts) | set(expect_counts) if counts.get(t) != expect_counts.get(t))
        raise BackupFailed(f"the backup's row counts differ in {', '.join(differ)}")


def take(conn: sqlite3.Connection, db_path: Path, label: str, *, expect_version: int,
         now: Optional[datetime] = None) -> Path:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    final = db_path.with_name(f"{db_path.name}.{label}-{stamp}")
    if final.exists():
        raise BackupFailed(f"{final.name} already exists")
    assert_test_write_allowed(final)
    temp = db_path.with_name(f".{final.name}.partial")
    if temp.exists():
        temp.unlink()
    try:
        expect_counts = _counts(conn)
        with closing(sqlite3.connect(str(temp))) as dest:
            conn.backup(dest)
            dest.execute("PRAGMA journal_mode=DELETE")
        with open(temp, "rb") as handle:
            os.fsync(handle.fileno())
        verify(temp, expect_version=expect_version, expect_counts=expect_counts)
        os.replace(temp, final)
        dir_fd = os.open(final.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except (BackupFailed, sqlite3.Error, OSError):
        for stale in (temp, Path(f"{temp}-wal"), Path(f"{temp}-shm"), Path(f"{temp}-journal")):
            if stale.exists():
                stale.unlink()
        raise
    logger.info("cplug_storage_backup", db=db_path.name, backup=final.name, version=expect_version)
    return final

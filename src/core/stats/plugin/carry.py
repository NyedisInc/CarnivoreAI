
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import List, Optional, Tuple

import structlog

logger = structlog.get_logger()

LEGACY_NAME = "cloude-stats.db"
RETIRED_INFIX = ".retired-"
SETTINGS_TABLES: Tuple[str, ...] = (
    "stats_meta", "stats_settings", "stats_disabled_spans", "stats_charts", "stats_annotations",
    "stats_tripwires", "stats_backfill", "stats_rule_sources", "stats_git_progress", "stats_git_markers",
    "stats_events", "stats_models_seen", "price_versions",
)
LIVE_TABLES: Tuple[str, ...] = (
    "dim_live", "activity_minute", "activity_hour", "coverage_minute", "coverage_hour", "quota_minute",
    "quota_hour", "stat_retention",
)
LEDGER_TABLES: Tuple[str, ...] = ("stats_answers",)


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone():
        return []
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def copy_tables(old: sqlite3.Connection, new: sqlite3.Connection, tables: Tuple[str, ...]) -> int:
    copied = 0
    for table in tables:
        have = _columns(old, table)
        if not have:
            continue
        if not _columns(new, table):
            for (sql,) in old.execute("SELECT sql FROM sqlite_master WHERE tbl_name = ? AND sql IS NOT NULL "
                                      "ORDER BY type = 'index'", (table,)):
                new.execute(sql)
        shared = [c for c in have if c in set(_columns(new, table))]
        cols = ", ".join(shared)
        rows = old.execute(f"SELECT {cols} FROM {table}").fetchall()
        new.executemany(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({', '.join('?' for _ in shared)})",
                        [tuple(r) for r in rows])
        copied += len(rows)
    return copied


def close_open_backfills(conn: sqlite3.Connection, state: str = "complete") -> int:
    if not _columns(conn, "stats_backfill"):
        return 0
    return conn.execute("UPDATE stats_backfill SET state = ?, updated_at = ? WHERE state IN ('requested', 'running')",
                        (state, int(time.time()))).rowcount


def carry_over(old: sqlite3.Connection, new: sqlite3.Connection) -> None:
    copy_tables(old, new, SETTINGS_TABLES + LIVE_TABLES + LEDGER_TABLES)
    close_open_backfills(new)


def retire_legacy(state_dir: Path, conn: sqlite3.Connection, today: Optional[str] = None) -> Optional[Path]:
    from src.core.db import transaction

    legacy = Path(state_dir) / LEGACY_NAME
    if not legacy.exists():
        return None
    stamp = today or time.strftime("%Y%m%d")
    retired = legacy.with_name(f"{LEGACY_NAME}{RETIRED_INFIX}{stamp}")
    n = 1
    while retired.exists():
        n += 1
        retired = legacy.with_name(f"{LEGACY_NAME}{RETIRED_INFIX}{stamp}-{n}")
    for suffix in ("-wal", "-shm", ""):
        part = Path(f"{legacy}{suffix}")
        if part.exists():
            os.replace(part, Path(f"{retired}{suffix}"))
    try:
        with closing(sqlite3.connect(retired.as_uri() + "?mode=ro", uri=True, timeout=30)) as old:
            with transaction(conn):
                copied = copy_tables(old, conn, SETTINGS_TABLES)
                close_open_backfills(conn)
    except sqlite3.Error as exc:
        logger.warning("stats_legacy_settings_unreadable", retired=retired.name, error=str(exc))
        copied = 0
    logger.info("stats_legacy_db_retired", retired=retired.name, settings_rows=copied)
    return retired

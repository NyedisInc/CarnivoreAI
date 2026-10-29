
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, Optional

import structlog

from src.core.db import DatastoreUnreadableError, db_path_for
from src.core.db_reuse import datastore_pool
from src.core.db_reuse.lent import LentConnection

logger = structlog.get_logger()


def lend_pooled_read(path: Path) -> Optional[LentConnection]:
    if not Path(path).exists():
        return None
    try:
        return datastore_pool.lend(path)
    except DatastoreUnreadableError as exc:
        logger.warning("name_read_datastore_unavailable", error=str(exc))
        return None


def lend_pooled_or_raise(path: Path) -> LentConnection:
    try:
        conn = datastore_pool.lend(path)
    except DatastoreUnreadableError as exc:
        logger.warning("name_read_datastore_unavailable", error=str(exc))
        raise
    try:
        conn.execute("PRAGMA schema_version").fetchone()
    except sqlite3.DatabaseError as exc:
        conn.close()
        datastore_pool.forget_if_broken(path, exc)
        raise DatastoreUnreadableError(f"{Path(path).name} cannot be read at {path}: {exc}", Path(path)) from exc
    return conn


def lend_for_state_dir(get_state_dir: Callable[[], Path]) -> Optional[LentConnection]:
    try:
        return lend_pooled_read(db_path_for(get_state_dir()))
    except Exception as exc:  # noqa: BLE001
        logger.debug("pooled_datastore_unavailable", error=str(exc))
        return None

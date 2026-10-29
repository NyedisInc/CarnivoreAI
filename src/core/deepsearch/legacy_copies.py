
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import structlog

from src.core.db import transaction
from src.core.deepsearch import constants as K
from src.core.deepsearch.live import store

logger = structlog.get_logger()


def retire(conn: sqlite3.Connection, state_dir: Path) -> int:
    folder = Path(state_dir) / K.BACKUP_COPY_DIR
    like = str(folder).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + os.sep + "%"
    ids = [int(r[0]) for r in conn.execute(f"SELECT id FROM {K.LIVE_TABLE} WHERE path LIKE ? ESCAPE '\\'", (like,))]
    if ids:
        with transaction(conn):
            for live_id in ids:
                store.delete_file(conn, live_id)
    removed = 0
    try:
        names = os.listdir(folder)
    except FileNotFoundError:
        return 0
    except OSError as exc:
        logger.warning("deepsearch_backup_copies_unreadable", error=str(exc)[:200])
        return 0
    for name in names:
        try:
            (folder / name).unlink()
            removed += 1
        except OSError as exc:
            logger.warning("deepsearch_backup_copy_not_removed", name=name, error=str(exc)[:200])
    try:
        folder.rmdir()
    except OSError as exc:
        logger.warning("deepsearch_backup_copies_folder_not_removed", error=str(exc)[:200])
    logger.info("deepsearch_backup_copies_retired", copies=removed, rows=len(ids))
    return removed

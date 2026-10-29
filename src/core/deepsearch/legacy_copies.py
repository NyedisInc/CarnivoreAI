"""Retire the plain copies the old backup lane (issue #1807) wrote under ``<state>/deepsearch-backup-copies/``.

Step 4 of the backup and archive build serves a conversation Claude Code deleted straight from the backup vault
(``vault_lane.py``, ``byte_source.py``), so no plain copy is needed and none is written. An install that ran the old lane
still has the folder and the index rows that point into it. Both are DERIVED cache (the same class as ``deepsearch.db``
itself on a version mismatch; the vault is the record), so they are removed once, at the first pass of a process: the rows in
one transaction, then the files, then the folder. With the backup plugin on, the vault lane indexes those conversations
again from the vault over the next passes; with it off the old lane would have dropped them too.

The inventory keeps claiming the folder (``inventory/file_claims.py``, ``state_files.py``) while this module exists, because
an install that has not run the new build yet still has it; remove those claims and this module in the hygiene pass after the
next release.
"""

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

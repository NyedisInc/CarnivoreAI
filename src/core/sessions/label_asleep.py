
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

import structlog

from src.core.db import DatastoreUnreadableError, connect, db_path_for, transaction
from src.core.session_label import set_label, validate_label

logger = structlog.get_logger()


def set_asleep_label(ident: str, label: str, *, state_dir: Path) -> Optional[tuple[str, Optional[str]]]:
    from src.core.crosstalk import directory

    validate_label(label)
    rows = directory._asleep_rows(state_dir)
    hits = [r for r in rows if str(r["session_uuid"]) == ident] or [r for r in rows if r.get("tmux_name") == ident]
    if len(hits) != 1:
        logger.info("asleep_label_no_unique_row", ident=ident, matches=len(hits))
        return None
    uuid = str(hits[0]["session_uuid"])
    try:
        with closing(connect(db_path_for(state_dir), create=False)) as conn:
            with transaction(conn):
                return (uuid, hits[0].get("tmux_name")) if set_label(conn, session_uuid=uuid, label=label) else None
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("asleep_label_write_failed", session_uuid=uuid, error=type(exc).__name__)
        return None

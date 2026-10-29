
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Dict, Iterable

import structlog

from src.cplugs.sdk.session_rows import SessionRowsUnreadable, StoredRow

logger = structlog.get_logger()


def read(keys: Iterable[str]) -> Dict[str, StoredRow]:
    wanted = sorted({k for k in keys if k})
    if not wanted:
        return {}
    from src.api.peer_auth import open_db  # noqa: PLC0415
    from src.core.db import DatastoreError  # noqa: PLC0415

    marks = ",".join("?" * len(wanted))
    try:
        with closing(open_db()) as conn:
            rows = conn.execute(f"SELECT session_uuid, project_id, archived_at FROM sessions WHERE session_uuid IN ({marks})", wanted).fetchall()
    except (sqlite3.Error, DatastoreError) as exc:
        logger.warning("cplug_session_rows_unreadable", error_type=type(exc).__name__, error=str(exc)[:200])
        raise SessionRowsUnreadable(type(exc).__name__) from exc
    return {str(r[0]): StoredRow(int(r[1]) if r[1] is not None else None, r[2] is not None) for r in rows}

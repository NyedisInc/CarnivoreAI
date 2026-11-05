
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

Row = Dict[str, Any]


class UnfilteredRows(Exception):

    def __init__(self, rows: List[Row]) -> None:
        super().__init__("replaced scan failed")
        self.rows = rows


def drop_replaced_rows(conn: sqlite3.Connection, rows: List[Row]) -> List[Row]:
    from src.core.db_models import SESSION_LIFECYCLE_RUNNING

    try:
        replaced = {
            int(r["parent_session_id"])
            for r in conn.execute(
                "SELECT parent_session_id FROM sessions"
                " WHERE lifecycle = ?"
                " AND parent_session_id IS NOT NULL",
                (SESSION_LIFECYCLE_RUNNING,),
            ).fetchall()
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "recent_replaced_scan_unavailable",
            error=str(exc),
            error_type=type(exc).__name__,
            note=(
                "could not read which rows a running session "
                "replaced; nothing excluded, so a duplicate may "
                "show rather than a session going missing"
            ),
        )
        raise UnfilteredRows(rows)
    if not replaced:
        return rows
    return [row for row in rows if row.get("id") not in replaced]


def read_stopped_rows(db_path: Path, include_archived: bool, include_automated: bool) -> List[Row]:
    from src.core import session_store
    from src.core.db_models import SESSION_LIFECYCLE_STOPPED
    from src.core.db_reuse.core_read import lend_pooled_or_raise

    with closing(lend_pooled_or_raise(db_path)) as conn:
        rows = session_store.list_sessions(
            conn,
            lifecycle=SESSION_LIFECYCLE_STOPPED,
            include_archived=include_archived,
            include_automated=include_automated,
        )
        return drop_replaced_rows(conn, rows)


def cached_rows(db_path: Path, include_archived: bool, include_automated: bool) -> List[Row]:
    from src.core.db_reuse.change_cache import HOT_READS

    try:
        kept = HOT_READS.fetch(
            db_path, ("recent_rows", include_archived, include_automated),
            lambda: read_stopped_rows(db_path, include_archived, include_automated),
        )
    except UnfilteredRows as unfiltered:
        kept = unfiltered.rows
    return [dict(row) for row in kept]


def closed_order(rows: List[Row]) -> List[Tuple[Row, Optional[str], Optional[str]]]:
    from src.core.db_models import SESSION_LIFECYCLE_STOPPED
    from src.core.session_sleep import is_asleep
    from src.core.sessions.closed_time import closed_time, order_recent

    stopped = [
        row for row in rows
        if row.get("lifecycle") == SESSION_LIFECYCLE_STOPPED and not is_asleep(row)
        and row.get("origin") != "peer"
    ]
    return [(row, *closed_time(row)) for row in order_recent(stopped)]

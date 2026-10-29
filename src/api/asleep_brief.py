
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from src.api import recreate_routes as rr
from src.core import session_sleep
from src.core.db_reuse.change_cache import HOT_READS
from src.core.automations import plugin_schedules
from src.core.session_roles import read as roles_read
from src.cplugs.sdk import ports
from src.api.error_response import api_error

logger = structlog.get_logger()


def brief_of(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"session_uuid": str(row.get("session_uuid")), "project_id": row.get("project_id"),
            "name": row.get("title") or row.get("tmux_name")}


def read_asleep_rows(db_path: Path) -> List[Dict[str, Any]]:
    from src.core.db_reuse.core_read import lend_pooled_or_raise  # noqa: PLC0415

    def load() -> List[Dict[str, Any]]:
        with closing(lend_pooled_or_raise(db_path)) as conn:
            return session_sleep.asleep_rows(conn)

    return [dict(row) for row in HOT_READS.fetch(db_path, ("asleep_rows",), load)]


async def asleep_brief() -> List[Dict[str, Any]]:
    from src.core.db import DatastoreUnreadableError  # noqa: PLC0415

    db_path = rr._db_path()
    if not db_path.exists():
        return []
    try:
        rows = await run_in_threadpool(read_asleep_rows, db_path)
    except DatastoreUnreadableError as exc:
        raise api_error(503, "datastore_unavailable", exc, step="asleep_brief") from exc
    return [brief_of(row) for row in rows]


async def for_listing_ports() -> Optional[List[Dict[str, Any]]]:
    if ports.get(plugin_schedules.PORT) is None and ports.get(roles_read.PORT) is None:
        return None
    try:
        return await asleep_brief()
    except HTTPException as exc:
        logger.warning("listing.asleep_brief.unreadable", status=exc.status_code)
        return None

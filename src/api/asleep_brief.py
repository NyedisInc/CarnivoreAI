
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from src.api import recreate_routes as rr
from src.core import session_sleep
from src.core.automations import plugin_schedules
from src.core.session_roles import read as roles_read
from src.cplugs.sdk import ports

logger = structlog.get_logger()


def brief_of(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"session_uuid": str(row.get("session_uuid")), "project_id": row.get("project_id"),
            "name": row.get("title") or row.get("tmux_name")}


def read_asleep_rows(db_path: Path) -> List[Dict[str, Any]]:
    from src.core.db import connect  # noqa: PLC0415

    with closing(connect(db_path, create=False)) as conn:
        return session_sleep.asleep_rows(conn)


async def asleep_brief() -> List[Dict[str, Any]]:
    """Every asleep session, newest first, in the light shape: one connection, one query, no theme or wake reads.

    Inputs: none (the install's datastore). Output: [{session_uuid, project_id, name}]; empty when the datastore does not exist yet.
    Raises: HTTPException 503 - the datastore exists but is unreadable (the same verdict ``GET /sessions/asleep`` answers).
    Example: await asleep_brief()  # [{'session_uuid': '7f3e...', 'project_id': 17, 'name': 'Garden Planner 2026'}]
    """
    from src.core.db import DatastoreUnreadableError  # noqa: PLC0415

    db_path = rr._db_path()
    if not db_path.exists():
        return []
    try:
        rows = await run_in_threadpool(read_asleep_rows, db_path)
    except DatastoreUnreadableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [brief_of(row) for row in rows]


async def for_listing_ports() -> Optional[List[Dict[str, Any]]]:
    """The light asleep list for one listing build's plugin ports, or None when no port wants it or it could not be read.

    Description: read only while the schedule or roles port is registered (the Task Manager is on). None makes each port read for
      itself, exactly as before, so an unreadable datastore keeps its old answer (the port's own read fails the same way).
    Inputs: none. Output: [{session_uuid, project_id, name}] | None.
    Example: asleep = await for_listing_ports()  # None while the Task Manager is off
    """
    if ports.get(plugin_schedules.PORT) is None and ports.get(roles_read.PORT) is None:
        return None
    try:
        return await asleep_brief()
    except HTTPException as exc:
        logger.warning("listing.asleep_brief.unreadable", status=exc.status_code)
        return None


from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from src.api.error_response import api_error
from src.api.auth import require_auth
from src.core.db import DatastoreError
from src.core.flow_data import mcp_events

router = APIRouter(tags=["mcp-events"], dependencies=[Depends(require_auth)])


class McpEvents(BaseModel):
    """The answer: ``events`` newest first, ``retention_days`` how long rows are kept."""

    events: List[Dict[str, Any]]
    retention_days: int


@router.get("/mcp-events", response_model=McpEvents)
async def list_mcp_events(tool: Optional[str] = None, session_id: Optional[str] = None, since: float = 0.0,
                          limit: int = Query(100, ge=1, le=mcp_events.READ_MAX)) -> McpEvents:
    """MCP tool calls, newest first, optionally one tool or one caller session.

    Inputs: tool; session_id (the caller's session id); since (epoch seconds); limit (1 to 500). Output: McpEvents.
    Description: 503 when the datastore cannot be read.
    """
    try:
        rows = await run_in_threadpool(lambda: mcp_events.recent(tool=tool, session_id=session_id, since=since, limit=limit))
    except (sqlite3.Error, DatastoreError) as exc:
        raise api_error(503, "datastore_unavailable", exc, step="mcp_events") from exc
    return McpEvents(events=rows, retention_days=mcp_events.RETENTION_DAYS)

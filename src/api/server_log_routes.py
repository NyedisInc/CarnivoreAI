
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Union

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from src.api.auth import require_auth
from src.core.server_log import LEVELS, ServerLogWatch, read_entries
from src.core.server_log.locate import server_log_path
from src.core.server_log.records import parse_cursor, read_page
from src.core.server_log.tail import DEFAULT_LINES, MAX_LINES
from src.api.error_response import api_error

logger = structlog.get_logger()

router = APIRouter(tags=["server-log"])


class ServerLogEntry(BaseModel):
    """One parsed log line."""

    timestamp: str
    level: str
    event: str
    fields: str


class ServerLogPage(BaseModel):
    """The tail answer: entries oldest first, and the level names that exist."""

    entries: List[ServerLogEntry]
    levels: List[str]


class ServerLogRecord(BaseModel):
    """One v2 record: a structlog event, or raw stderr text, with its continuation lines."""

    id: str
    timestamp: str
    level: str
    source: str
    event: str
    fields: Dict[str, str]
    lines: List[str]
    dropped_lines: int
    traceback: bool
    continues: bool
    approx_time: bool


class ServerLogPageV2(BaseModel):
    """The v2 answer: records oldest first, the cursors, and whether the read skipped (gap) or restarted (reset)."""

    version: int = 2
    records: List[ServerLogRecord]
    levels: List[str]
    head: Optional[str]
    before: Optional[str]
    gap: bool
    reset: bool


def watch_for(app_state) -> ServerLogWatch:
    watch = getattr(app_state, "server_log_watch", None)
    if watch is None:
        watch = ServerLogWatch(server_log_path)
        app_state.server_log_watch = watch
    return watch


def _wanted_levels(levels: str) -> List[str]:
    wanted = [name for name in (part.strip() for part in levels.split(",")) if name]
    if any(name not in LEVELS for name in wanted):
        raise HTTPException(status_code=422, detail="levels must be from: " + ", ".join(LEVELS))
    return wanted


@router.get("/server-log", response_model=Union[ServerLogPageV2, ServerLogPage], dependencies=[Depends(require_auth)])
async def get_server_log(
    request: Request,
    limit: int = Query(DEFAULT_LINES, ge=1, le=MAX_LINES),
    levels: str = Query(",".join(LEVELS), max_length=64),
    v: int = Query(1, ge=1, le=2),
    since: Optional[str] = Query(None, max_length=48),
    before: Optional[str] = Query(None, max_length=48),
) -> Union[ServerLogPageV2, ServerLogPage]:
    """The newest log lines (v1) or records (v2) now, and a lease that keeps the watcher pushing while this client looks."""
    wanted = _wanted_levels(levels)
    try:
        since_at, before_at = parse_cursor(since), parse_cursor(before)
    except ValueError as exc:
        raise api_error(422, "invalid_request", exc, step="get_server_log") from exc
    if since_at is not None and before_at is not None:
        raise HTTPException(status_code=422, detail="name since or before, not both")
    watch_for(request.app.state).touch()
    try:
        if v == 2:
            page = await asyncio.to_thread(
                read_page, server_log_path(), since=since_at, before=before_at, levels=wanted, limit=limit,
            )
            return ServerLogPageV2(levels=list(LEVELS), **page)
        entries = await asyncio.to_thread(read_entries, server_log_path(), wanted, limit)
    except OSError as exc:
        logger.warning("server_log_unreadable", error=type(exc).__name__, version=v)
        raise HTTPException(status_code=503, detail="the server log could not be read") from exc
    return ServerLogPage(entries=[ServerLogEntry(**e) for e in entries], levels=list(LEVELS))

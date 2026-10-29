from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.auth import require_auth
from src.core.stats import config, events
from src.api.error_response import api_error

router = APIRouter(prefix="/stats", tags=["stats"], dependencies=[Depends(require_auth)])


@router.get("/event-log", response_model=None)
async def get_event_log(request: Request, from_: datetime = Query(alias="from"),
                        to: datetime = Query(), kind: str | None = None,
                        limit: int = Query(100, ge=1, le=200),
                        cursor: int = Query(0, ge=0, le=100000)) -> dict:
    """Return typed events in [from, to), newest first: ids and numbers only, never content."""
    if from_.tzinfo is None or to.tzinfo is None or from_ >= to:
        raise HTTPException(422, detail={"code": "invalid_range"})
    store = getattr(request.app.state, "stats_store", None)
    if store is None:
        raise HTTPException(503, detail={"code": "stats_unavailable"})
    try:
        await asyncio.to_thread(config.require_enabled, store)
        return await asyncio.to_thread(events.list_events, store, start=int(from_.timestamp()),
                                       end=int(to.timestamp()), kind=kind, limit=limit, cursor=cursor)
    except config.StatsOff as exc:
        raise HTTPException(409, detail={"code": "stats_off", "message": "stats off"}) from exc
    except ValueError as exc:
        raise api_error(422, "invalid_stats_request", exc) from exc

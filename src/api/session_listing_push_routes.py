
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.auth import require_auth

logger = structlog.get_logger()
router = APIRouter()

MAX_SNAPSHOT_AGE_SECONDS = 60.0


@router.get("/sessions/listing", dependencies=[Depends(require_auth)])
async def listing_snapshot(
    request: Request,
    max_age: Optional[float] = Query(None, ge=0, le=MAX_SNAPSHOT_AGE_SECONDS),
) -> Dict[str, Any]:
    """Every pushed collection with the sequence it stands at.

    Description: answered from the publisher's own state (a pass runs first
      when that state is stale), so the snapshot and the deltas after it
      share one sequence. Owner only: a paired Mac keeps `/sessions/list`.
    Inputs: request (Request); max_age (float | None, query) - seconds of
      staleness the caller accepts, 0 to 60; omitted means the publisher's own.
    Output: dict - {"stream": str, "seq": int, "collections": {name:
      {"rows": [...], "ok": bool, "status": int | None, "detail": any,
      "meta": {...}}}} for list, attachable, records, asleep and recent.
    Raises: HTTPException 503 - this server runs no listing push.
    Example: GET /api/v1/sessions/listing
    """
    publisher = getattr(request.app.state, "listing_publisher", None)
    if publisher is None:
        raise HTTPException(status_code=503, detail="listing push unavailable")
    return await publisher.snapshot(max_age)

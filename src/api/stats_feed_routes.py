
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from src.api import peer_auth
from src.api.auth import require_auth
from src.core.federation import peer_fanout
from src.core.stats_feed import install
from src.core.stats_feed.model import WINDOWS

router = APIRouter(prefix="/stats", tags=["stats"], dependencies=[Depends(require_auth)])
peer_router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/feed", response_model=None)
async def get_stats_feed(request: Request, window: str = Query("1h"), lease: bool = Query(True)) -> Response:
    """The window's token feed. Inputs: window - 1h, 5h, 1d or 7d; lease - keep the feed pushing for this reader.

    Output: JSON ``{v, rev, window, bucket_seconds, start, now, state, in, out, totals, rate, sources}``; ``null``
      in a bar, ``totals`` or ``rate`` means not measured. Raises: HTTPException 422 for an unknown window.
    Example: GET /api/v1/stats/feed?window=1h -> {"state":"ok","in":[...60],"out":[...60],...}
    """
    if window not in WINDOWS:
        raise HTTPException(422, detail={"code": "invalid_stats_window", "message": f"window is one of {', '.join(WINDOWS)}"})
    body = await install(request.app.state).body(window, lease=lease)
    return Response(content=body, media_type="application/json")


@peer_router.get("/feed/local", response_model=None, dependencies=[Depends(peer_auth.require_peer_sessions)])
async def get_stats_feed_local(request: Request) -> dict:
    feed = install(request.app.state)
    if peer_fanout.is_peer_call(request):
        feed.touch_peer()
    return await feed.local_answer()

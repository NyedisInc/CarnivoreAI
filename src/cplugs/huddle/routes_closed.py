
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict, Optional

from fastapi import HTTPException, Query

from src.cplugs.huddle import closures, service
from src.cplugs.huddle.routes import Ctx, router, run_store
from src.cplugs.sdk import CplugContext


@router.get("/closed")
async def get_closed(q: str = Query("", max_length=400), cursor: Optional[str] = Query(None, max_length=200),
                     limit: int = Query(closures.DEFAULT_LIMIT, ge=1, le=closures.MAX_LIMIT), list: Optional[str] = Query(None, max_length=200),  # noqa: A002
                     ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """One page of closed tasks. Output: {items, next_cursor}. Raises: 400 ``closed_cursor_invalid``."""
    store = service.store(ctx)

    def read() -> Dict[str, Any]:
        with closing(store._read_connection()) as conn:
            return closures.page(conn, q=q, cursor=cursor, limit=limit, list_key=list)

    try:
        return await run_store(read)
    except closures.CursorError as exc:
        raise HTTPException(status_code=400, detail={"code": "closed_cursor_invalid", "detail": str(exc)}) from exc

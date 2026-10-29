
from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request

from src.api.auth import require_auth
from src.core import toast_history

logger = structlog.get_logger()

router = APIRouter(tags=["toasts"])

STORAGE_IN_MEMORY = "process_memory"

MAX_UNACKED_LIMIT = 500


def _buckets(request: Request) -> Dict[str, Any]:
    services = getattr(request.app.state, "services", None)
    inbox = services.toasts if services is not None else None
    return dict(toast_history.buckets_from_inbox(inbox))


@router.get(
    "/toasts",
    response_model=None,
    dependencies=[Depends(require_auth)],
)
async def list_all_toasts(
    request: Request,
    unacked: bool = Query(
        True,
        description=(
            "Return only records the user has not dismissed. True is the "
            "default because this route's job is 'what still wants "
            "attention', not 'what has ever happened' - that is /toasts/history."
        ),
    ),
    limit: Optional[int] = Query(
        None, description="Page size. Defaults to 100, capped at 500."
    ),
) -> Dict[str, Any]:
    """List toasts across EVERY session, newest first.

    Description: the cross-session raise path. The client polls this from
        whatever screen it is on and feeds the result into the same
        ``ToastManager.backfill`` the per-session attach backfill already
        uses, so a record arriving by this route and by the WebSocket
        renders once - ``add()`` dedupes on ``toast.id``.
    Args:
        request: the incoming request, for ``app.state``.
        unacked: filter to undismissed records only.
        limit: page size; clamped into range rather than rejected.
    Returns:
        ``{'toasts': [...], 'total': int, 'unacked_only': bool}``. An
        empty list is a real answer and never an error.
    """
    records = toast_history.collect_toasts(_buckets(request), unacked_only=unacked)
    capped = toast_history.clamp_limit(limit, default=MAX_UNACKED_LIMIT)
    items, total, _ = toast_history.page(records, limit=capped, offset=0)
    return {
        "toasts": [t.model_dump(mode="json") for t in items],
        "total": total,
        "unacked_only": unacked,
    }


@router.get(
    "/toasts/history",
    response_model=None,
    dependencies=[Depends(require_auth)],
)
async def list_toast_history(
    request: Request,
    limit: Optional[int] = Query(
        None, description="Page size. Defaults to 100, capped at 500."
    ),
    offset: int = Query(0, description="How many records to skip."),
) -> Dict[str, Any]:
    """Page back through every toast this server run has recorded.

    Description: read-only scrollback for punchlist item 8, so a
        notification that was raised while the owner was elsewhere can
        still be found afterwards. Dismissed and undismissed records are
        both included - the whole point is to see what was missed - and
        each carries ``acknowledged`` so the client can mark which.
    Args:
        request: the incoming request, for ``app.state``.
        limit: page size; clamped into range rather than rejected.
        offset: paging cursor. Negative is treated as 0.
    Returns:
        ``{'toasts': [...], 'total': int, 'limit': int, 'offset': int,
        'next_offset': int | None, 'summary': {...}, 'storage': str}``.
        ``next_offset`` is None on the last page, so a client advances by
        reading a field rather than re-deriving the boundary arithmetic.
        ``summary`` counts the WHOLE set, not the page.
    """
    records = toast_history.collect_toasts(_buckets(request), unacked_only=False)
    capped = toast_history.clamp_limit(limit)
    if offset < 0:
        offset = 0
    items, total, next_offset = toast_history.page(
        records, limit=capped, offset=offset
    )
    logger.debug(
        "toast_history_read", total=total, returned=len(items), offset=offset
    )
    return {
        "toasts": [t.model_dump(mode="json") for t in items],
        "total": total,
        "limit": capped,
        "offset": offset,
        "next_offset": next_offset,
        "summary": toast_history.summarize(records),
        "storage": STORAGE_IN_MEMORY,
    }

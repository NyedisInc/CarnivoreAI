
from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from src.api.auth import require_auth
from src.api.ui_show_resolve import NoSuchItem, resolve
from src.core.ui_show import last_window, pointer
from src.models.ui_show import ActivityRequest, ShowRequest, ShowResponse

logger = structlog.get_logger()

router = APIRouter(tags=["ui-show"], dependencies=[Depends(require_auth)])


def _refused(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail})


@router.post("/ui/activity", status_code=204)
async def report_activity(body: ActivityRequest) -> Response:
    """Record that a window just had user input, so it is the window used last. Output: 204."""
    last_window.touch(body.client_id)
    return Response(status_code=204)


@router.post("/ui/activity/gone", status_code=204)
async def report_gone(body: ActivityRequest) -> Response:
    """Forget a window that closed; the window used before it is the one used last again. Output: 204, also for an unknown id."""
    last_window.gone(body.client_id)
    return Response(status_code=204)


@router.get("/ui/show")
async def get_show() -> Dict[str, Optional[Dict[str, Any]]]:
    """The show pointer a window reads on the push. Output: {show: pointer | None}."""
    return {"show": pointer.current()}


@router.post("/ui/show", response_model=ShowResponse)
async def show_item(body: ShowRequest, request: Request) -> ShowResponse:
    """Bring one item into view in the named window (default: the window used last), and tell every window once.

    Inputs: body {kind, id, target_client_id?}; request. Output: ShowResponse.
    Errors: 404 ui_show_not_found; 409 ui_show_no_window.
    Example: POST /api/v1/ui/show {"kind": "layout", "id": "5f0c..."}
    """
    try:
        found = await resolve(request.app, body.kind, body.id)
    except NoSuchItem as exc:
        raise _refused(404, "ui_show_not_found", exc.detail) from exc
    target = body.target_client_id or last_window.current()
    if target is None or (body.target_client_id and not last_window.known(target)):
        raise _refused(409, "ui_show_no_window", "no window has been used since the server started, or that window is closed; click or type in a Carnivore window, then try again")
    stored = pointer.point(body.kind, found.id, found.title, target, found.tmux_session)
    logger.info("ui_show_pointed", kind=body.kind, item=found.id, seq=stored["seq"])
    return ShowResponse(kind=body.kind, id=found.id, title=found.title, seq=stored["seq"])

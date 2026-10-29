
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from src.api import peer_ws_auth
from src.api.peer_auth import require_peer_sessions
from src.api.websocket import connection_manager
from src.core import toast_auto_ack
from src.models import (
    CreateToastRequest,
    SuccessResponse,
    Toast,
    ToastAckMessage,
    ToastNewMessage,
)
from typing import List

logger = structlog.get_logger()
router = APIRouter()


def _owner_key(request: Request, session_id: str) -> str:
    if getattr(request.state, "peer_grant", None) is None:
        return session_id
    return peer_ws_auth.local_session_id(request.app.state.services.registry, session_id)




@router.get(
    "/sessions/{session_id}/toasts",
    response_model=List[Toast],
    dependencies=[Depends(require_peer_sessions)],
)
async def list_session_toasts(
    request: Request, session_id: str, unacked: bool = False
):
    """List toasts for a session, optionally filtered to unacked-only.

    Used by the client on (re)attach to backfill any toast that fired
    while the browser was disconnected. Newest-first. Returns an empty
    list (NOT 404) when the session has no toasts - the launchpad polls
    speculatively and an empty array is the right success shape.
    """
    return request.app.state.services.toasts.get(_owner_key(request, session_id), unacked)


@router.post(
    "/sessions/{session_id}/toasts",
    response_model=Toast,
    status_code=201,
    dependencies=[Depends(require_peer_sessions)],
)
async def create_session_toast(
    request: Request, session_id: str, body: CreateToastRequest
):
    """Synthetic toast creation - record + broadcast to the session.

    INTENTIONALLY TEMPORARY for v0.7.0 Part 2: lets the client and storage
    layer be exercised end-to-end without a real Claude Code hook. Part 3
    will add a hook-driven endpoint with different auth semantics; THIS
    surface remains useful for manual testing and is the canonical entry
    point for synthetic-load tests.

    NOT GATED BY THE PER-SESSION NOTIFICATION MUTE, and that is a decision
    rather than an oversight. The mute suppresses the alerts an AGENT
    raises about itself; this route is the app's own channel, and the
    plan it comes from preserves action errors explicitly. Muting a
    session must not stop the app telling its user that something the
    user just did failed. The EXTERNAL push is still covered: the event
    ``record_toast`` emits is stamped with the session's policy, so the
    dispatcher drops it for a muted session either way.

    Returns 404 when the session id is unknown.
    """
    session_manager = request.app.state.session_manager
    try:
        toast = session_manager.record_toast(
            session_id=session_id,
            kind=body.kind,
            title=body.title,
            body=body.body,
            notify_type="session.posted",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if body.detail is not None:
        toast = request.app.state.services.toasts.describe(
            toast.session_id, toast.id, body.detail
        ) or toast

    try:
        await connection_manager.broadcast_to_session(
            session_id,
            ToastNewMessage(toast=toast).model_dump_json(),
        )
    except Exception as exc:
        logger.warning("toast_broadcast_failed", session_id=session_id, error=str(exc))

    return toast


@router.post(
    "/toasts/{toast_id}/ack",
    response_model=SuccessResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def ack_toast(request: Request, toast_id: str, session_id: str):
    """Mark a toast acknowledged and broadcast the ack to the session.

    ``session_id`` is a required query parameter (not body) so this is a
    cleanly bookmarkable / curlable URL. The broadcast lets OTHER browsers
    attached to the same session dismiss the toast in lockstep - no
    localStorage cross-tab sync needed.

    Idempotent at the storage layer: a double-click won't re-broadcast.

    THE SCOPING IS STILL REAL, and it is what keeps a dismissal per
    session now that raising is global (see src/api/toast_routes.py):
    ``ack_toast`` walks ONLY ``session_id``'s bucket, so acking session
    B's toast id under session A leaves B's record untouched. The
    isolation lives in the storage walk, not in the status code.
    """
    session_manager = request.app.state.session_manager
    session_id = _owner_key(request, session_id)
    changed = request.app.state.services.toasts.ack(
        session_id, toast_id, toast_auto_ack.ACK_REASON_DISMISSED
    )
    if not changed:
        return SuccessResponse(success=True, message="No-op")

    try:
        await connection_manager.broadcast_to_session(
            session_id,
            ToastAckMessage(toast_id=toast_id).model_dump_json(),
        )
    except Exception as exc:
        logger.warning(
            "toast_ack_broadcast_failed",
            session_id=session_id,
            toast_id=toast_id,
            error=str(exc),
        )

    return SuccessResponse(success=True, message="Toast acknowledged")

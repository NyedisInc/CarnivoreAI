
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import routed_remote
from src.api.websocket import connection_manager
from src.core import session_change_notice
from src.core.swarm import leaders as swarm_leaders
from src.models import RenameSessionRequest, SessionRenamedMessage
from src.api.error_response import api_error

logger = structlog.get_logger()
router = APIRouter()




@router.patch(
    "/sessions/{session_id}/name",
    dependencies=[Depends(require_peer_sessions)],
)
async def rename_session_endpoint(
    request: Request, session_id: str, body: RenameSessionRequest
):
    """Set a session's user-facing LABEL, live or asleep. The tmux name never moves.

    An ASLEEP session is addressed by its ``session_uuid`` (or a tmux name only one asleep row carries); its
    stored row takes the label and the wake resumes under it.

    STALE DOC CORRECTED. This docstring described the endpoint's behaviour
    before the label split and outlived it: it named a
    ``^[A-Za-z0-9_-]{1,64}$`` validator, a 409 and a 500 that the body
    below had already stopped being able to produce. The comment block
    above this function explained the new design correctly the whole time,
    which is exactly how a stale docstring survives - the accurate prose
    sat next to it and nobody re-read the paragraph underneath.

    Validates ``new_name`` with ``session_label.validate_label``: at most
    ``LABEL_MAX_CHARS`` (200) characters, non-empty after stripping, no
    control characters. Spaces, punctuation and non-ASCII are all ACCEPTED
    - the label is never handed to tmux, so tmux's constraints do not
    apply to it. Returns:

      * 400 - empty, too long, or carrying a control character
      * 404 - no tmux session this app has a record of
      * 200 - success; body is the updated ``SessionInfo``

    There is no 409: two sessions may carry the same label, because a
    label identifies nothing. There is no 500 for a failed tmux rename,
    because no tmux rename happens.

    On success the server broadcasts ``session.renamed`` to every WS bound
    to ``session_id`` so all attached tabs update their displayed name +
    ``document.title``. The broadcast is best-effort - broadcast failures
    log a warning but do not roll back the rename (the in-memory state is
    already authoritative).
    """
    session_manager = request.app.state.session_manager
    remote = routed_remote(session_manager, session_id)

    from src.core.session_label import InvalidLabel, validate_label

    try:
        new_name = validate_label(body.new_name)
    except InvalidLabel as exc:
        logger.info(
            "api_rename_session_rejected_invalid_label",
            session_id=session_id,
            reason=str(exc),
        )
        raise api_error(400, "invalid_request", exc, step="rename_session_endpoint") from exc

    logger.info(
        "api_rename_session_request",
        session_id=session_id,
        new_name=new_name,
    )

    if remote is not None:
        from src.core.hosts.remote_controls import set_label

        session_id = remote.session_id
        stored = await run_in_threadpool(set_label, session_manager, remote, new_name)
    else:
        stored = session_manager.set_session_label(session_id, new_name)
        if not stored:
            from src.config import settings
            from src.core.sessions.label_asleep import set_asleep_label

            asleep = await run_in_threadpool(
                set_asleep_label, session_id, new_name, state_dir=settings.get_state_dir()
            )
            if asleep:
                return await _finish_asleep_rename(request, *asleep, new_name)
    if not stored:
        raise HTTPException(
            status_code=404,
            detail=(
                "That session could not be labelled - it is not a tmux "
                "session this app has a record of."
            ),
        )
    if remote is None:
        held = getattr(getattr(session_manager, "_registry", None), "sessions", {}).get(session_id)
        await swarm_leaders.follow_session_rename(getattr(held, "tmux_session", None) or session_id, new_name)
    info = None
    try:
        info = await session_manager.get_session_info(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "rename_session_info_unavailable",
            session_id=session_id,
            error=str(exc),
            note="the label write succeeded; only the response shape is degraded",
        )

    try:
        await connection_manager.broadcast_to_session(
            session_id,
            SessionRenamedMessage(
                session_id=session_id, new_name=new_name
            ).model_dump_json(),
        )
    except Exception as exc:
        logger.warning(
            "rename_session_broadcast_failed",
            session_id=session_id,
            error=str(exc),
        )

    session_change_notice.publish(
        request.app.state,
        session_change_notice.build_rename_notice(
            session_id=session_id, new_name=new_name
        ),
    )

    if info is not None:
        return info
    return {
        "renamed": True,
        "session": session_id,
        "label": new_name,
        "detail": "renamed; no live session attached to describe",
    }


async def _finish_asleep_rename(request: Request, session_uuid: str, tmux_name: Optional[str], new_name: str) -> dict:
    await swarm_leaders.follow_session_rename(tmux_name, new_name)
    session_change_notice.publish(
        request.app.state,
        session_change_notice.build_rename_notice(session_id=session_uuid, new_name=new_name),
    )
    return {"renamed": True, "session": session_uuid, "label": new_name, "asleep": True,
            "detail": "renamed; the session is asleep and wakes under this name"}


import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import routed_remote
from src.core.agent_family_display import resolve_family_for_display
from src.api.session_name_known import known_tmux_names, strip_adopted_prefix
from src.config import wrapper_reader
from src.models.utc_time import utc_now
from src.models import (
    Session,
    SessionInfo,
    SessionStats,
    SessionStatus,
    SetUnreadRequest,
    SuccessResponse,
    UpdatePinnedThemeRequest,
    UpdateThemeRequest,
)
from typing import Optional

logger = structlog.get_logger()
router = APIRouter()


_PINNED_THEME_ALIAS_WARNED: bool = False


async def _apply_session_theme(
    session_manager,
    themes,
    owned_tmux,
    registry,
    session_name: str,
    theme_id: Optional[str],
) -> SessionInfo:
    remote = routed_remote(session_manager, session_name)
    if remote is not None:
        from src.core.hosts.remote_controls import set_pin

        set_pin(session_manager, remote, theme_id)
        logger.info("api_set_remote_session_theme", host=remote.backend.host_key,
                    session_id=remote.session_id, theme_id=theme_id)
        info = await session_manager.get_session_info(session_id=remote.session_id)
        if info is not None:
            return info
        raise HTTPException(status_code=404, detail=f"Unknown session {session_name!r}")
    session_name = strip_adopted_prefix(session_name)

    known_names: set[str] = known_tmux_names(session_manager, owned_tmux)

    if session_name not in known_names:
        logger.info(
            "session_theme_set_404",
            session_name=session_name,
            known_names=sorted(known_names),
        )
        raise HTTPException(
            status_code=404,
            detail=f"Unknown session {session_name!r}",
        )

    matched_sid: Optional[str] = None
    matched_working_dir: Optional[str] = None
    for sid, b in registry.backends.items():
        if b.tmux_session == session_name:
            matched_sid = sid
            sess_obj = registry.get_session(sid)
            if sess_obj is not None:
                matched_working_dir = sess_obj.working_dir
            break

    session_manager.set_pinned_theme(session_name, theme_id)

    logger.info(
        "api_set_session_theme",
        session_name=session_name,
        theme_id=theme_id,
        working_dir=matched_working_dir,
    )

    if matched_sid is not None:
        info = await session_manager.get_session_info(session_id=matched_sid)
        if info is not None:
            return info

    placeholder_session = Session(
        id=f"pinned:{session_name}",
        pty_pid=None,
        working_dir=matched_working_dir or "",
        status=SessionStatus.STOPPED,
        created_at=utc_now(),
        last_activity=utc_now(),
        pinned_theme=theme_id,
    )
    placeholder_family, placeholder_family_source = resolve_family_for_display(
        None, wrapper_reader.configured_wrappers()
    )
    return SessionInfo(
        session=placeholder_session,
        recent_logs=[],
        local_servers=[],
        stats=SessionStats(
            total_commands=0, uptime_seconds=0, log_lines=0, local_servers=0
        ),
        session_backend="none",
        tmux_session=session_name,
        agent_type=None,
        agent_family=placeholder_family.name if placeholder_family else None,
        agent_family_source=placeholder_family_source,
        pinned_theme=theme_id,
    )


@router.patch(
    "/sessions/{session_name}/theme",
    response_model=SessionInfo,
    dependencies=[Depends(require_peer_sessions)],
)
async def set_session_theme(
    request: Request, session_name: str, body: UpdateThemeRequest
):
    """Set (or clear) the project-scoped theme for a session.

    Supersedes ``PATCH /sessions/{name}/pinned-theme``. The theme id is
    recorded against this session's tmux name, so two sessions running
    out of one folder can hold two different themes and each keeps its
    own across a server restart. Clearing drops the session back to its
    project's ``.cc.theme`` default.

    Body shape: ``{"theme_id": "<id>"}`` or ``{"theme_id": null}`` (or
    empty string) to clear. The session is validated against the same
    known-tmux-names set used by the legacy route - owned ∪ active ∪
    attachable probe - so this endpoint can't become an arbitrary KV
    store while still accepting pins for detached-but-alive sessions.

    The response is the live ``SessionInfo`` when the named session is
    active; otherwise a minimal echo whose ``pinned_theme`` field
    carries the new value.
    """
    session_manager = request.app.state.session_manager
    return await _apply_session_theme(
        session_manager,
        request.app.state.services.themes,
        request.app.state.services.owned_tmux,
        request.app.state.services.registry,
        session_name,
        body.theme_id,
    )


@router.patch(
    "/sessions/{session_name}/unread",
    response_model=SuccessResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def set_session_unread(
    request: Request, session_name: str, body: SetUnreadRequest
):
    """Manually mark (or clear) a session unread for followup.

    feat/hook-driven-status - ``session_name`` is the literal tmux session
    name (same convention as ``/sessions/{session_name}/theme``), so this
    works whether the session is currently attached to or only attachable.
    Persisted server-side (not localStorage) so the flag follows the user
    across browsers/devices - see ``SessionManager.set_manual_unread``.

    ONE FLAG. ``/sessions/list`` reports this and the automatic flag as one
    ``unread``, so every surface agrees. Setting it writes the follow-up
    flag onto the session's ROW (issue #749), so it survives a sleep and a
    wake; False marks the session read outright, and so does opening its
    tab while it is at rest.
    """
    session_manager = request.app.state.session_manager
    session_name = strip_adopted_prefix(session_name)
    if body.unread and session_name not in known_tmux_names(session_manager, request.app.state.services.owned_tmux):
        raise HTTPException(status_code=404, detail=f"Unknown session {session_name!r}")
    session_manager.set_manual_unread(session_name, body.unread)
    return SuccessResponse(
        success=True,
        message=f"Session {'marked' if body.unread else 'cleared'} unread",
    )


@router.patch(
    "/sessions/{session_name}/pinned-theme",
    response_model=SessionInfo,
    dependencies=[Depends(require_peer_sessions)],
    deprecated=True,
)
async def set_pinned_theme(
    request: Request, session_name: str, body: UpdatePinnedThemeRequest
):
    """DEPRECATED v0.7.0 - use ``PATCH /sessions/{session_name}/theme``.

    Kept as a routing alias for ONE release so v0.6.x clients keep
    working through an upgrade window. Internally forwards to the same
    code path as the new endpoint - the theme id is recorded as this
    session's own pin regardless of which route the client hits. The
    response shape is unchanged.

    Will be REMOVED in v0.8.x. New clients MUST use ``/theme``.
    """
    global _PINNED_THEME_ALIAS_WARNED
    if not _PINNED_THEME_ALIAS_WARNED:
        _PINNED_THEME_ALIAS_WARNED = True
        logger.warning(
            "route_deprecated_pinned_theme",
            session_name=session_name,
            replacement="PATCH /sessions/{session_name}/theme",
            removal_version="v0.8.x",
        )
    session_manager = request.app.state.session_manager
    return await _apply_session_theme(
        session_manager,
        request.app.state.services.themes,
        request.app.state.services.owned_tmux,
        request.app.state.services.registry,
        session_name,
        body.pinned_theme,
    )


from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query, Request

from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import routed_remote
from src.api.recreate_routes import router as recreate_router
from src.api.restart_account_routes import router as restart_account_router
from src.models import (
    RestartPlanPreview,
    RestartPreviewOption,
    RestartPreviewResponse,
)
from src.api.error_response import api_error

logger = structlog.get_logger()

router = APIRouter(tags=["sessions"])

router.include_router(recreate_router)
router.include_router(restart_account_router)


@router.get(
    "/sessions/restart/preview",
    response_model=RestartPreviewResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def restart_preview(
    request: Request,
    session_name: str = Query(
        ..., description="Literal tmux session name to preview a restart for"
    ),
):
    """Report what restarting this session would do, without doing it.

    Returns the baseline plan (nothing picked) plus one predicted
    outcome per configured launch wrapper, all derived from a single
    reading of the pane so every option on screen answers a question
    about the same observed state.

    Raises:
        HTTPException(400): the name contains ``:`` or ``.``.
        HTTPException(500): a genuine, unexpected server fault.
    """
    session_manager = request.app.state.session_manager
    remote = routed_remote(session_manager, session_name)

    try:
        if remote is not None:
            from src.core.hosts.remote_restart import preview_remote

            preview = await preview_remote(session_manager, remote.key)
        else:
            preview = await session_manager.restart_preview(session_name)
    except ValueError as exc:
        raise api_error(400, "session_restart_invalid", exc, name=session_name, step="preview") from exc
    except Exception as exc:  # noqa: BLE001
        raise api_error(500, "session_restart_preview_failed", exc, name=session_name) from exc

    return RestartPreviewResponse(
        name=preview.name,
        current_agent_type=preview.current_agent_type,
        pane_state=preview.pane_state,
        unchanged=RestartPlanPreview(
            kind=preview.unchanged.kind,
            detail=preview.unchanged.detail,
            command=preview.unchanged.command,
            actionable=preview.unchanged.actionable,
            conversation=preview.unchanged.conversation,
        ),
        projected=RestartPlanPreview(
            kind=preview.projected.kind,
            detail=preview.projected.detail,
            command=preview.projected.command,
            actionable=preview.projected.actionable,
            conversation=preview.projected.conversation,
        ),
        options=[
            RestartPreviewOption(
                agent_type=o.agent_type,
                label=o.label,
                family=o.family or None,
                icon=o.icon,
                is_current=o.is_current,
                resolvable=o.resolvable,
                actionable_now=o.actionable_now,
                kind=o.kind,
                detail=o.detail,
                projected_kind=o.projected_kind,
                projected_detail=o.projected_detail,
                command=o.command,
                conversation=o.conversation,
                same_as_unchanged=o.same_as_unchanged,
            )
            for o in preview.options
        ],
        wrappers_status=preview.wrappers_status,
        launch_display=preview.launch_display,
    )


from __future__ import annotations

from contextlib import closing
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.core.account_switch.launch_env import _config_path
from src.core.pack.identity.home import ProjectMovedAway
from src.core.pack.move import account as account_launch
from src.api.peer_auth import require_peer_sessions
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.session_agent_choice import (
    resolve_wrapper_offers,
    validate_agent_choice,
)
from src.core.session_imported_restart import (
    is_imported_row,
    imported_extra_args,
    plan_imported_restart,
    resume_directory,
)
from src.core.session_respawn import (
    PANE_UNKNOWN,
    RESPAWN_AGENT,
    RESPAWN_CANNOT_DETERMINE,
)
from src.models import (
    RestartPlanPreview,
    RestartPreviewOption,
    RestartPreviewResponse,
)
from src.api.error_response import api_error

logger = structlog.get_logger()

router = APIRouter(tags=["sessions"])


class ImportedRestartRequest(BaseModel):
    """Restart one imported conversation under a chosen wrapper.

    ``agent_type`` is REQUIRED and there is no unpicked path, unlike the
    pane restart. A pane at least has a recorded start command to fall
    back on; an imported row has nothing, so an unpicked restart could
    only ever hand back a bare login shell - the exact outcome the pane
    path's whole warning apparatus exists to stop a user walking into.
    Rather than warn about it, this refuses to offer it.
    """

    session_uuid: str = Field(..., description="sessions.session_uuid")
    agent_type: str = Field(..., description="wrapper id from the preview")


class ImportedRestartResponse(BaseModel):
    """What the restart did, or why it did nothing."""

    status: str = Field(
        ...,
        description=(
            "'started' when a tmux session was created for this "
            "conversation, 'refused' when a gate declined. A refusal is a "
            "200 with this field, never a silent success"
        ),
    )
    session_uuid: str = Field(..., description="the row that was acted on")
    session_id: Optional[str] = Field(
        None, description="the live session id, on 'started' only"
    )
    conversation: str = Field(
        ...,
        description=(
            "'resumed' | 'none_recorded' | 'unknown', derived from the "
            "argv actually run so the claim cannot outrun the command"
        ),
    )
    command: Optional[str] = Field(None, description="what was run")
    working_dir: Optional[str] = Field(
        None, description="the spelling the session was created in"
    )
    detail: str = Field("", description="one sentence, fit to show verbatim")
    code: Optional[str] = Field(
        None,
        description="on 'refused' for an unknown launch profile: 'wrapper_needed' (old clients and peers read it)",
    )
    codes: List[str] = Field(
        default_factory=list,
        description="every wire code for that refusal: 'wrapper_needed' and 'launch_profile_needed' (issue #1257)",
    )


def _db_path():
    from src.config import settings

    return db_path_for(settings.get_state_dir())


def _read_row(session_uuid: str) -> Dict[str, Any]:
    try:
        with closing(connect(_db_path(), create=False)) as conn:
            found = conn.execute(
                "SELECT * FROM sessions WHERE session_uuid = ?", (session_uuid,)
            ).fetchone()
        return {
            "row": dict(found) if found is not None else None,
            "row_read_ok": True,
        }
    except (DatastoreUnreadableError, OSError) as exc:
        logger.warning(
            "imported_restart_row_unreadable",
            session_uuid=session_uuid,
            error=str(exc),
        )
        return {"row": None, "row_read_ok": False}


def _require_imported(state: Dict[str, Any], session_uuid: str) -> Dict[str, Any]:
    if not state["row_read_ok"]:
        raise HTTPException(
            status_code=503,
            detail="the datastore could not be read, so this session's restart could not be evaluated",
        )
    row = state["row"]
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"no session carries the uuid {session_uuid!r}"
        )
    if not is_imported_row(row):
        raise HTTPException(
            status_code=409,
            detail=(
                f"session {session_uuid!r} has a tmux identity "
                f"({row.get('tmux_name')!r}), so it restarts through "
                "GET /sessions/restart/preview and POST /sessions/respawn"
            ),
        )
    return row


@router.get(
    "/sessions/imported/restart/preview",
    response_model=RestartPreviewResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def imported_restart_preview(
    session_uuid: str = Query(..., description="sessions.session_uuid"),
) -> RestartPreviewResponse:
    """What restarting this imported conversation would do, changing nothing.

    Description: reads the row, measures which spelling of its working
      directory holds the transcript, and runs the SAME plan builder the
      action runs, once per configured wrapper. Every offer is resolved
      with the SAME ``--resume`` fragment the action will pass, so the
      command shown and the command run are one string by construction.

      ``pane_state`` is ``'unknown'`` and ``unchanged`` is
      ``cannot_determine``: there is no pane, so neither its state nor
      the outcome of an unpicked restart is a fact anybody measured. That
      is the honest answer, and it is what keeps the picker from enabling
      a button for an option that does not exist here.
    Raises: HTTPException 404 (no such session), 409 (it has a tmux
      identity), 503 (the datastore could not be read).
    """
    from src.api.launch_profile_errors import unknown_profile_codes
    from src.config import settings

    state = await run_in_threadpool(_read_row, session_uuid)
    row = _require_imported(state, session_uuid)

    extra_args = imported_extra_args(row, row_read_ok=True)
    directory = await run_in_threadpool(
        resume_directory,
        row.get("working_dir"),
        row.get("claude_session_uuid"),
        family=row.get("agent_family"),
    )
    offers = resolve_wrapper_offers(settings, extra_args=extra_args)

    unchanged_plan = plan_imported_restart(
        row,
        row_read_ok=True,
        choice_verdict=None,
        choice_command=None,
        choice_detail=(
            "an imported conversation has no recorded start command, so "
            "there is nothing to restart until a wrapper is picked"
        ),
        directory=directory,
    )

    options = []
    for offer in offers or []:
        choice = validate_agent_choice(
            settings, offer.agent_type, extra_args=extra_args
        )
        plan = plan_imported_restart(
            row,
            row_read_ok=True,
            choice_verdict=choice.verdict,
            choice_command=choice.command,
            choice_detail=choice.detail,
            agent_type=offer.agent_type,
            directory=directory,
        )
        options.append(
            RestartPreviewOption(
                agent_type=offer.agent_type,
                label=offer.label,
                family=offer.family or None,
                icon=offer.icon,
                is_current=False,
                resolvable=bool(offer.command),
                actionable_now=plan.actionable,
                kind=plan.kind,
                detail=plan.detail,
                projected_kind=plan.kind,
                projected_detail=plan.detail,
                command=plan.command,
                conversation=plan.conversation,
            )
        )

    plan_preview = RestartPlanPreview(
        kind=unchanged_plan.kind,
        detail=unchanged_plan.detail,
        command=None,
        actionable=False,
        conversation=unchanged_plan.conversation,
    )
    return RestartPreviewResponse(
        name=str(row.get("title") or session_uuid),
        current_agent_type=row.get("agent_type"),
        pane_state=PANE_UNKNOWN,
        unchanged=plan_preview,
        projected=plan_preview,
        options=options,
        wrappers_status="unavailable" if offers is None else "ok",
    )


@router.post(
    "/sessions/imported/restart",
    response_model=ImportedRestartResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def imported_restart(
    request: Request, body: ImportedRestartRequest
) -> ImportedRestartResponse:
    """Restart an imported row, refusing a second restart of it while one runs.

    Description: the route seam. Holds the per-row restart claim
      (src/core/restart_inflight.py) around :func:`_imported_restart`, so
      a double click answers 409 instead of creating a second session.
    Inputs: request (Request). body (ImportedRestartRequest).
    Output: ImportedRestartResponse.
    Raises: HTTPException 409 when a restart of this row is in progress,
      plus everything :func:`_imported_restart` raises.
    """
    from src.core import restart_inflight

    try:
        with restart_inflight.claim(body.session_uuid):
            return await _imported_restart(request, body)
    except restart_inflight.RestartInFlightError as exc:
        raise api_error(409, restart_inflight.IN_PROGRESS_CODE, exc) from exc


async def _imported_restart(
    request: Request, body: ImportedRestartRequest
) -> ImportedRestartResponse:
    from src.api.launch_profile_errors import unknown_profile_codes
    from src.api.swarm_switch_routes import refuse_held_body
    from src.config import settings

    await refuse_held_body(body.session_uuid)
    state = await run_in_threadpool(_read_row, body.session_uuid)
    row = _require_imported(state, body.session_uuid)

    extra_args = imported_extra_args(row, row_read_ok=True)
    directory = await run_in_threadpool(
        resume_directory,
        row.get("working_dir"),
        row.get("claude_session_uuid"),
        family=row.get("agent_family"),
    )
    choice = validate_agent_choice(
        settings, body.agent_type, model=row.get("model"), extra_args=extra_args
    )
    plan = plan_imported_restart(
        row,
        row_read_ok=True,
        choice_verdict=choice.verdict,
        choice_command=choice.command,
        choice_detail=choice.detail,
        agent_type=body.agent_type,
        directory=directory,
    )
    if plan.kind != RESPAWN_AGENT or not plan.actionable:
        status = 400 if plan.kind == RESPAWN_CANNOT_DETERMINE and not row else 200
        logger.info(
            "imported_restart_refused",
            session_uuid=body.session_uuid,
            kind=plan.kind,
        )
        return ImportedRestartResponse(
            status="refused",
            session_uuid=body.session_uuid,
            conversation=plan.conversation,
            command=plan.command,
            working_dir=plan.working_dir,
            detail=plan.detail,
            **unknown_profile_codes(settings, body.agent_type, choice.verdict),
        )

    launch = await run_in_threadpool(account_launch.launch_for_session, _config_path(), body.session_uuid)
    if launch is None:
        return ImportedRestartResponse(
            status="refused", session_uuid=body.session_uuid, conversation=plan.conversation, command=plan.command,
            working_dir=plan.working_dir, detail=account_launch.NOT_USABLE_DETAIL, code=account_launch.NOT_USABLE_CODE)
    manager = request.app.state.session_manager
    try:
        session = await manager.create_session(
            session_id=body.session_uuid,
            extra_env=launch["extra_env"],
            claude_account=launch["account_id"],
            working_dir=plan.working_dir,
            auto_start_claude=True,
            agent_type=body.agent_type,
            model=row.get("model"),
            agent_extra_args=extra_args,
            label=plan.label,
            reuse_session_id=plan.reuse_session_id,
        )
    except ProjectMovedAway:
        raise
    except Exception as exc:  # noqa: BLE001
        raise api_error(500, "session_restart_failed", exc, session_uuid=body.session_uuid, step="imported") from exc

    logger.info(
        "imported_restart_started",
        session_uuid=body.session_uuid,
        agent_type=body.agent_type,
        conversation=plan.conversation,
    )
    return ImportedRestartResponse(
        status="started",
        session_uuid=body.session_uuid,
        session_id=getattr(session, "id", None),
        conversation=plan.conversation,
        command=plan.command,
        working_dir=plan.working_dir,
        detail=plan.detail,
    )


from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.api.peer_auth import require_peer_sessions
from src.core.session_agent_evidence import choose_agent_evidence
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.session_agent_choice import (
    resolve_wrapper_offers,
    validate_agent_choice,
)
from src.core.session_imported_restart import (
    imported_extra_args,
    resume_directory,
)
from src.core.session_recreate import plan_recreate
from src.core.session_recreate_presence import (
    TMUX_UNKNOWN,
    TmuxPresence,
    pane_state_for,
    tmux_presence,
)
from src.models import (
    RestartPlanPreview,
    RestartPreviewOption,
    RestartPreviewResponse,
)
from src.api.error_response import api_error

logger = structlog.get_logger()

router = APIRouter(tags=["sessions"])


class RecreateRequest(BaseModel):
    """Recreate one dead session under a chosen wrapper.

    ``agent_type`` is REQUIRED and there is no unpicked path. A pane at
    least has a recorded ``#{pane_start_command}`` to fall back on; a
    session whose tmux is gone has nothing, so an unpicked recreate could
    only ever hand back a bare login shell - the exact outcome the pane
    path's whole warning apparatus exists to stop a user walking into.
    Rather than warn about it, this refuses to offer it.
    """

    session_uuid: str = Field(..., description="sessions.session_uuid")
    agent_type: str = Field(..., description="wrapper id from the preview")
    account_id: Optional[str] = Field(
        None,
        description=(
            "claude account to start on (GET /sessions/{session_uuid}/restart/accounts); "
            "omit to use the session's pinned account, else the active one"
        ),
    )
    account_pinned: bool = Field(
        False,
        description="With account_id: true saves it for this session, false clears any saved account",
    )


class RecreateResponse(BaseModel):
    """What the recreate did, or why it did nothing."""

    status: str = Field(
        ...,
        description=(
            "'started' when a new tmux session was created on this "
            "session's existing row, 'refused' when a gate declined. A "
            "refusal is a 200 with this field, never a silent success"
        ),
    )
    session_uuid: str = Field(..., description="the row that was acted on")
    session_name: Optional[str] = Field(
        None,
        description=(
            "the tmux name the row carries, read from the record rather "
            "than supplied by the caller"
        ),
    )
    session_id: Optional[str] = Field(
        None, description="the live session id, on 'started' only"
    )
    tmux_session: Optional[str] = Field(
        None,
        description=(
            "the tmux name actually taken. The SAME name is asked for so "
            "name-scoped per-device state survives, but the create path "
            "uniquifies on collision, so this is reported rather than "
            "assumed"
        ),
    )
    presence: str = Field(
        ...,
        description=(
            "'gone' | 'present' | 'unknown' - the socket measurement the "
            "decision was gated on. Only 'gone' can act"
        ),
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


def _db_path() -> Path:
    from src.config import settings

    return db_path_for(settings.get_state_dir())


def _socket_name() -> str:
    from src.config import settings
    from src.core.tmux_backend import DEFAULT_SOCKET_NAME

    try:
        return settings.load_auth_config().session.tmux_socket_name
    except (OSError, ValueError, AttributeError):
        return DEFAULT_SOCKET_NAME


def _measure_presence(name: str, socket_name: str) -> TmuxPresence:
    from src.config import settings
    from src.core.tmux_backend import SESSION_PREFIX, TmuxBackend

    try:
        probe = TmuxBackend.for_external(
            session_name=name,
            working_dir=Path(settings.default_working_dir).expanduser(),
            on_output=None,
            socket_name=socket_name,
        )
        listing = probe.discover_existing()
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("recreate_presence_unmeasured", name=name, error=str(exc))
        return TmuxPresence(
            outcome=TMUX_UNKNOWN,
            detail=(
                "the tmux socket could not be listed, so whether this "
                "session is still running was not evaluated"
            ),
        )
    return tmux_presence(
        name,
        listing_ok=bool(listing.ok),
        listing_complete=bool(listing.complete),
        names=list(listing.sessions or []),
        namespace_prefix=SESSION_PREFIX,
    )


def _read_row(session_uuid: str) -> Dict[str, Any]:
    try:
        with closing(connect(_db_path(), create=False)) as conn:
            found = conn.execute(
                "SELECT * FROM sessions WHERE session_uuid = ?", (session_uuid,)
            ).fetchone()
    except (DatastoreUnreadableError, OSError) as exc:
        logger.warning(
            "recreate_row_unreadable", session_uuid=session_uuid, error=str(exc)
        )
        return {"row": None, "row_read_ok": False}
    return {"row": dict(found) if found is not None else None, "row_read_ok": True}


def _resolved(state: Dict[str, Any], session_uuid: str) -> Dict[str, Any]:
    from src.core.session_recreate import has_tmux_identity

    if not state["row_read_ok"]:
        raise HTTPException(
            status_code=503,
            detail=(
                "the datastore could not be read, so this session's "
                "recreate could not be evaluated"
            ),
        )
    row = state["row"]
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"no session carries the uuid {session_uuid!r}"
        )
    if (row.get("host_key") or "local") != "local":
        raise HTTPException(status_code=409, detail={
            "code": "remote_host",
            "detail": f"session {session_uuid!r} runs on host {row['host_key']}; "
                      "a remote session is never recreated on this machine"})
    if not has_tmux_identity(row):
        raise HTTPException(
            status_code=409,
            detail=(
                f"session {session_uuid!r} has never had a tmux session, so "
                "it restarts through GET /sessions/imported/restart/preview "
                "and POST /sessions/imported/restart"
            ),
        )
    return row


def _gather(
    session_uuid: str, row_overrides: Optional[Dict[str, Any]] = None, *, fresh: bool = False,
    corpus_root: Optional[Path] = None,
) -> Dict[str, Any]:
    row = _resolved(_read_row(session_uuid), session_uuid)
    if row_overrides:
        row = dict(row)
        for key in ("claude_session_uuid", "working_dir"):
            if row_overrides.get(key):
                row[key] = row_overrides[key]
    if fresh:
        row = {**row, "claude_session_uuid": None}
    socket_name = str(row.get("tmux_socket") or _socket_name())
    name = _safe(str(row.get("tmux_name") or ""))
    presence = _measure_presence(name, socket_name)
    extra_args = imported_extra_args(row, row_read_ok=True)
    wd, conv = row.get("working_dir"), row.get("claude_session_uuid")
    directory = resume_directory(wd, conv, corpus_root=corpus_root, family=row.get("agent_family"))
    return {
        "row": row,
        "name": name,
        "presence": presence,
        "extra_args": extra_args,
        "directory": directory,
        "socket": socket_name,
    }


def _safe(name: str) -> str:
    from src.core.tmux_transport.target import check_target_name

    try:
        return check_target_name(name)
    except ValueError as exc:
        raise api_error(400, "session_name_invalid", exc, name=name) from exc


@router.get(
    "/sessions/recreate/preview",
    response_model=RestartPreviewResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def recreate_preview(
    session_uuid: str = Query(..., description="sessions.session_uuid"),
) -> RestartPreviewResponse:
    """What recreating this session would do, changing nothing.

    Description: one socket listing, one row read, one directory
      measurement, one config read, and the SAME ``plan_recreate`` the
      action runs - once with nothing picked and once per configured
      wrapper. Every offer is resolved with the SAME ``--resume``
      fragment the action will pass, so the command shown and the command
      run are one string by construction.

      ``pane_state`` reports the socket measurement in the model's own
      three words, so a session measured PRESENT paints ``alive`` and
      every option arrives ``actionable_now=False``. A recreate is never
      offered over a running agent, and the refusal is a sentence rather
      than a missing button.
    Raises: HTTPException 400 (the row carries a name tmux would misread
      as a target), 404 (no such record), 409 (the row never had a tmux
      session), 503 (datastore unreadable).
    """
    from src.config import settings

    facts = await run_in_threadpool(_gather, session_uuid)
    row = facts["row"]
    name = facts["name"]
    presence: TmuxPresence = facts["presence"]

    offers = resolve_wrapper_offers(
        settings, model=row.get("model"), extra_args=facts["extra_args"]
    )

    recorded = choose_agent_evidence(
        memory_agent_type=None,
        memory_from_fingerprint=False,
        row_agent_type=row.get("agent_type"),
        row_family_source=row.get("agent_family_source"),
    )
    recorded_type = None if recorded.from_process else recorded.agent_type
    unchanged = plan_recreate(
        row,
        row_read_ok=True,
        presence=presence,
        choice_verdict=None,
        choice_command=None,
        choice_detail=(
            "a session whose tmux is gone has no recorded start command "
            "left to fall back on, so there is nothing to run until a "
            "wrapper is picked"
        ),
        directory=facts["directory"],
    )
    baseline_actionable = False

    options: List[RestartPreviewOption] = []
    for offer in offers or []:
        choice = validate_agent_choice(
            settings,
            offer.agent_type,
            model=row.get("model"),
            extra_args=facts["extra_args"],
        )
        plan = plan_recreate(
            row,
            row_read_ok=True,
            presence=presence,
            choice_verdict=choice.verdict,
            choice_command=choice.command,
            choice_detail=choice.detail,
            agent_type=offer.agent_type,
            directory=facts["directory"],
        )
        is_recorded = bool(recorded_type) and offer.agent_type == recorded_type
        if is_recorded and plan.actionable:
            unchanged, baseline_actionable = plan, True
        options.append(
            RestartPreviewOption(
                agent_type=offer.agent_type,
                same_as_unchanged=is_recorded and plan.actionable,
                label=offer.label,
                family=offer.family or None,
                icon=offer.icon,
                is_current=offer.agent_type == row.get("agent_type"),
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

    preview_plan = RestartPlanPreview(
        kind=unchanged.kind,
        detail=unchanged.detail,
        command=None,
        actionable=baseline_actionable,
        conversation=unchanged.conversation,
    )
    logger.info(
        "recreate_preview",
        name=name,
        presence=presence.outcome,
        listed=presence.listed,
        offers=len(offers) if offers is not None else None,
        conversation=unchanged.conversation,
    )
    return RestartPreviewResponse(
        name=str(row.get("title") or name),
        current_agent_type=row.get("agent_type"),
        pane_state=pane_state_for(presence),
        unchanged=preview_plan,
        projected=preview_plan,
        options=options,
        wrappers_status="unavailable" if offers is None else "ok",
    )


@router.post(
    "/sessions/recreate",
    response_model=RecreateResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def recreate_session(
    request: Request, body: RecreateRequest
) -> RecreateResponse:
    """Create a new tmux session for a dead one, on the row it already has.

    Description: A RESTART MEANS A RESUME. There is no pane to respawn
      into, so this creates a session - in the spelling of the working
      directory that actually holds the transcript, under the wrapper the
      caller picked, with ``--resume <uuid>`` - and ``reuse_session_id``
      records the new tmux instance ONTO the existing row through
      ``session_restart.rebind_instance``. The row keeps its
      ``sessions.id`` and ``session_uuid``, so the project binding, the
      title, the conversation link, the pinned theme, the unread key and
      the v24 group membership all ride along untouched.

      THE SAME TMUX NAME IS ASKED FOR so name-scoped per-device browser
      state survives, and it is free by construction: the gate only
      passes when that name was measured ABSENT from the socket. The
      create path's own uniquify-on-collision rule still applies against
      records this app holds, so the name actually taken is REPORTED
      rather than assumed.

      A REFUSAL IS A 200 WITH ``status='refused'``, matching both other
      restart paths: the SERVER worked and a GATE declined, and a 500
      would blame the server for a state it correctly detected.
    Raises: HTTPException 400, 404, 409, 503, and 500 only on a genuine
      fault.
    """
    from src.api.recreate_action import recreate_by_uuid
    from src.core import restart_inflight

    try:
        with restart_inflight.claim(body.session_uuid):
            return await recreate_by_uuid(
                body.session_uuid,
                body.agent_type,
                get_manager=lambda: request.app.state.session_manager,
                account_id=body.account_id,
                account_pinned=body.account_pinned,
            )
    except restart_inflight.RestartInFlightError as exc:
        raise api_error(409, restart_inflight.IN_PROGRESS_CODE, exc) from exc

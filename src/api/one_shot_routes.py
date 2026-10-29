
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, NamedTuple, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.peer_auth import require_peer_sessions
from src.core.attention.pane_agent_proof import registered_agent_in_foreground
from src.core.session_one_shot_gate import (
    DIALOG_UNREADABLE,
    PROMPT_READY_STATUSES,
    OneShotRefused,
    PANE_DIALOG_OPEN,
    QUIET_REFUSALS,
    StatusUnconfirmed,
    check_can_paste,
    sanitize_body,
)
from src.core.session_status import KNOWN_SHELL_COMMANDS, STATUS_NOTICE, STATUS_UNKNOWN
from src.core.tmux_one_shot import PasteNotSettledError, PasteNotSubmittedError
from src.api.error_response import api_error

logger = structlog.get_logger()
router = APIRouter()

PASTE_UNSUPPORTED: str = "paste_unsupported"

PASTE_NOT_SETTLED: str = "paste_not_settled"
PASTE_NOT_SUBMITTED: str = "paste_not_submitted"


class OneShotRequest(BaseModel):
    """The body to paste into the session's pane.

    Inputs (fields): text (str) - the prompt. Refused if it holds an ESC
        byte; other control characters except newline and tab are stripped
        and counted.
    Output: n/a - a request model.
    Example: OneShotRequest(text="summarise this repo")
    """

    text: str = Field(..., description="The prompt to paste, at most 64 KiB")
    idle_only: bool = Field(default=False, description="Require a ready prompt (idle, or finished but unread), rechecked under the paste lock")


class OneShotResponse(BaseModel):
    """What the server actually did with the body.

    Inputs (fields): pasted_bytes (int) - UTF-8 length of the body after
        stripping, which is what tmux received. stripped_count (int) - how
        many control characters were removed. submitted (bool) - whether
        the single Enter was sent, which on a 200 is always True and is
        stated rather than implied.
    Output: n/a - a response model.
    Example: OneShotResponse(pasted_bytes=12, stripped_count=0,
        submitted=True)
    """

    pasted_bytes: int = Field(..., description="Bytes handed to tmux")
    stripped_count: int = Field(
        ..., description="Control characters removed from the body"
    )
    submitted: bool = Field(..., description="True when the one Enter was sent")


def _refuse(code: str, message: str, session_id: str) -> HTTPException:
    (logger.debug if QUIET_REFUSALS.get() else logger.info)(
        "one_shot_refused", session_id=session_id, code=code, reason=message
    )
    return HTTPException(
        status_code=409, detail={"code": code, "message": message}
    )


async def _read_pane_row(backend: Any, tmux_name: Optional[str]) -> Optional[dict]:
    if not tmux_name:
        return None
    listing = await asyncio.to_thread(backend.list_pane_status_all)
    if not listing.ok or not listing.complete:
        logger.info(
            "one_shot_pane_listing_unusable",
            tmux_session=tmux_name,
            reason=listing.reason,
            refused_rows=listing.refused_rows,
        )
        return None
    for row in listing.sessions:
        if row.get("name") == tmux_name:
            return row
    return None


async def _foreground_agent_proven(
    row: Optional[dict], tmux_name: Optional[str], claude_session_uuid: Optional[str],
    agent_type: Optional[str] = None,
) -> bool:
    if row is None:
        return False
    reads_as_shell = (row.get("pane_current_command") or "").strip() in KNOWN_SHELL_COMMANDS
    if not reads_as_shell and (agent_type or "").strip():
        return False
    return await asyncio.to_thread(
        registered_agent_in_foreground,
        tmux_name=tmux_name,
        pane_id=row.get("pane_id"),
        pane_pid=row.get("pid"),
        session_started_epoch=row.get("created_at_epoch"),
        claude_session_uuid=claude_session_uuid,
    )


async def _read_pane_signals(
    backend: Any, tmux_name: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    row = await _read_pane_row(backend, tmux_name)
    if row is None:
        return (None, None)
    return (row.get("pane_current_command"), row.get("pane_dead"))


class GatedBody(NamedTuple):

    session: Any
    backend: Any
    clean: Any
    gate: Callable[[], Awaitable[None]]
    pane_command: Optional[str]
    activity_status: Optional[str]
    startup_gate: Optional[str]


async def paste_through_gates(
    request: Request, session_id: str, text: str, *, idle_only: bool = False,
    expected_epoch: int | None = None, expected_uuid: str | None = None, fresh_dialog_check: bool = False,
) -> OneShotResponse:
    gated = await check_through_gates(request, session_id, text, idle_only=idle_only,
                                      expected_epoch=expected_epoch, expected_uuid=expected_uuid,
                                      fresh_dialog_check=fresh_dialog_check)
    return await paste_gated(gated, session_id)


async def check_through_gates(
    request: Request, session_id: str, text: str, *, idle_only: bool = False,
    expected_epoch: int | None = None, expected_uuid: str | None = None, fresh_dialog_check: bool = False,
) -> GatedBody:
    services = request.app.state.services
    registry = services.registry
    session = registry.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "session_not_found",
                "message": f"no session is registered as {session_id!r}",
            },
        )

    backend = registry.get_backend(session_id)
    if backend is None:
        raise _refuse(
            "session_gone",
            "the session has no live backend, so there is no pane to paste into",
            session_id,
        )

    try:
        clean = sanitize_body(text)
    except OneShotRefused as refusal:
        raise _refuse(refusal.code, refusal.message, session_id)

    async def gate() -> Tuple[Optional[str], Optional[str], Optional[str]]:
        from src.core.approvals.dialog_gate import CLEAR, OPEN, dialog_verdict, is_agent_pane
        pane_row = await _read_pane_row(backend, session.tmux_session)
        pane_command = pane_row.get("pane_current_command") if pane_row else None
        pane_dead = pane_row.get("pane_dead") if pane_row else None
        info = await request.app.state.session_manager.get_session_info(
            session_id=session_id
        )
        if expected_uuid is not None:
            from src.core.crosstalk.directory import _session_details
            row_id = info.session_row_id if info is not None else None
            details = await asyncio.to_thread(_session_details, [row_id] if row_id is not None else [])
            if not row_id or details.get(row_id, (None,))[0] != expected_uuid:
                raise OneShotRefused("receiver_instance_changed", "receiver is a different pane instance")
        if expected_epoch is not None and (info is None or info.session.tmux_created_epoch != expected_epoch):
            raise OneShotRefused("receiver_instance_changed", "receiver is a different pane instance")
        status = info.activity_status if info is not None else None
        gate_state = info.startup_gate if info is not None else None
        agent_type = info.agent_type if info is not None else session.agent_type
        proven = await _foreground_agent_proven(
            pane_row, session.tmux_session,
            info.claude_session_uuid if info is not None else None,
            agent_type,
        )
        verdict: Optional[str] = None
        try:
            check_can_paste(
                pane_current_command=pane_command,
                pane_dead=pane_dead,
                agent_type=agent_type,
                activity_status=status,
                startup_gate=gate_state,
                foreground_agent_proven=proven,
            )
        except StatusUnconfirmed as unconfirmed:
            if status != STATUS_UNKNOWN or info is None or not is_agent_pane(info):
                raise unconfirmed
            verdict = await dialog_verdict(request.app, session_id)
            if verdict == OPEN:
                raise OneShotRefused(PANE_DIALOG_OPEN, "a dialog is open in the pane right now")
            if verdict != CLEAR:
                raise OneShotRefused(DIALOG_UNREADABLE, "the pane's dialog state could not be read")
        if idle_only and status not in PROMPT_READY_STATUSES:
            raise OneShotRefused(PANE_DIALOG_OPEN, "crosstalk paste waits for a ready prompt (idle, or finished but unread)")
        if fresh_dialog_check or status == STATUS_NOTICE:
            if verdict is None:
                verdict = await dialog_verdict(request.app, session_id)
            if verdict == OPEN:
                raise OneShotRefused(PANE_DIALOG_OPEN, "a dialog is open in the pane right now")
            if verdict != CLEAR:
                raise OneShotRefused(DIALOG_UNREADABLE, "the pane's dialog state could not be read")
        return (pane_command, status, gate_state)

    async def locked_gate() -> None:
        await gate()

    try:
        pane_command, activity_status, startup_gate = await gate()
    except OneShotRefused as refusal:
        raise _refuse(refusal.code, refusal.message, session_id)
    return GatedBody(session, backend, clean, locked_gate, pane_command, activity_status, startup_gate)


async def paste_gated(gated: GatedBody, session_id: str) -> OneShotResponse:
    session, backend, clean = gated.session, gated.backend, gated.clean
    logger.info(
        "one_shot_paste_accepted",
        session_id=session_id,
        tmux_session=session.tmux_session,
        pane_current_command=gated.pane_command,
        agent_type=session.agent_type,
        activity_status=gated.activity_status,
        startup_gate=gated.startup_gate,
        bytes=clean.byte_length,
        stripped_count=clean.stripped_count,
    )

    try:
        await backend.paste_and_submit(clean.text, gate=gated.gate)
    except OneShotRefused as refusal:
        raise _refuse(refusal.code, refusal.message, session_id)
    except PasteNotSubmittedError as exc:
        raise _refuse(PASTE_NOT_SUBMITTED, str(exc), session_id)
    except PasteNotSettledError as exc:
        raise _refuse(PASTE_NOT_SETTLED, str(exc), session_id)
    except NotImplementedError as exc:
        raise _refuse(PASTE_UNSUPPORTED, str(exc), session_id)
    except RuntimeError as exc:
        raise api_error(500, "session_paste_failed", exc, session_id=session_id) from exc

    return OneShotResponse(
        pasted_bytes=clean.byte_length,
        stripped_count=clean.stripped_count,
        submitted=True,
    )


@router.post(
    "/sessions/{session_id}/skills/one-shot",
    response_model=OneShotResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def one_shot_paste(
    session_id: str, body: OneShotRequest, request: Request
) -> OneShotResponse:
    """Paste one body into a live agent pane and submit it with one Enter.

    Description: sanitises the body, confirms the three positive pane
        signals, then pastes and submits. Nothing reaches tmux until every
        check has passed, and the Enter is sent only after the pane is
        MEASURED to have changed.
    Inputs: session_id (str) - either id shape. body (OneShotRequest).
        request (Request) - for the registry and the activity tracker.
    Output: OneShotResponse - what was pasted and what was stripped.
    Raises: HTTPException 404 when the session is unknown; 409 carrying a
        ``code`` for every refusal; 500 only when tmux itself failed.
    Example: POST /sessions/ses_1/skills/one-shot {"text": "hello"}
    """
    from src.core.swarm import delivery as swarm_delivery

    return await swarm_delivery.paste_as_data(request, session_id, body.text, f"one_shot:{session_id}", idle_only=body.idle_only)

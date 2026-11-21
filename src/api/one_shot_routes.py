
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.error_response import api_error
from src.api.peer_auth import require_peer_sessions
from src.core.sessions import guarded_paste
from src.core.sessions.guarded_paste import GateOptions, PasteFailed, PasteRefused, PasteSessionNotFound

logger = structlog.get_logger()
router = APIRouter()


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


def paste_refusal_to_http(refusal: PasteRefused) -> HTTPException:
    if isinstance(refusal, PasteSessionNotFound):
        return HTTPException(status_code=404, detail={"code": refusal.code, "message": refusal.message})
    if isinstance(refusal, PasteFailed):
        return api_error(500, "session_paste_failed", refusal.__cause__ or refusal, session_id=refusal.session_id)
    return HTTPException(status_code=409, detail={"code": refusal.code, "message": refusal.message})


async def paste_through_gates(request: Any, session_id: str, text: str, **gate_options: Any) -> OneShotResponse:
    try:
        pasted = await guarded_paste.paste_through_gates(request.app.state, session_id, text, GateOptions(**gate_options))
    except PasteRefused as refusal:
        raise paste_refusal_to_http(refusal) from refusal
    return OneShotResponse(pasted_bytes=pasted.pasted_bytes, stripped_count=pasted.stripped_count, submitted=pasted.submitted)


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

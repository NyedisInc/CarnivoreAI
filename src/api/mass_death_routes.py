
from __future__ import annotations

import uuid as uuid_lib
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.error_response import api_error
from src.api.auth import require_auth
from src.core.mass_death import detector, notice, resume

logger = structlog.get_logger()
router = APIRouter(tags=["sessions"], dependencies=[Depends(require_auth)])


class MassDeathResumeRequest(BaseModel):
    """Body of the resume. ``session_uuids`` omitted means the latest mass death's sessions."""

    session_uuids: Optional[List[str]] = Field(default=None, max_length=resume.MAX_SESSIONS, description="session_uuid of each session to resume")


class MassDeathSessionResult(BaseModel):
    """One session's result: ``woken`` (note queued) or ``refused`` (``detail`` says why)."""

    session_uuid: str
    status: str
    detail: str = ""


class MassDeathResumeResponse(BaseModel):
    """What the resume did, per session, with the totals."""

    woken: int
    refused: int
    sessions: List[MassDeathSessionResult]


def _targets(body: Optional[MassDeathResumeRequest]) -> List[str]:
    listed = body.session_uuids if body and body.session_uuids is not None else None
    if listed is None:
        event = detector.DETECTOR.last_event
        if event is None:
            raise HTTPException(status_code=404, detail="no mass pane death on record; name the sessions in session_uuids")
        listed = list(event.session_uuids)
    for value in listed:
        try:
            uuid_lib.UUID(value)
        except (AttributeError, TypeError, ValueError):
            raise HTTPException(status_code=400, detail="session_uuids must be session UUIDs") from None
    return listed


@router.post("/sessions/mass-death/resume", response_model=MassDeathResumeResponse)
async def resume_mass_death(request: Request, body: Optional[MassDeathResumeRequest] = None) -> MassDeathResumeResponse:
    """Wake each listed session and give it the interruption note; close the alert when any woke.

    Inputs: request (Request); body (MassDeathResumeRequest | None). Output: MassDeathResumeResponse.
    Raises: HTTPException 400, 404 (see the module docstring).
    Example: POST /api/v1/sessions/mass-death/resume {"session_uuids": ["<uuid>"]}
    """
    targets = _targets(body)
    try:
        report = await resume.resume_all(request.app.state, targets)
    except ValueError as exc:
        raise api_error(400, "invalid_request", exc) from exc
    if report.woken:
        notice.resolve()
    return MassDeathResumeResponse(
        woken=report.woken, refused=report.refused,
        sessions=[MassDeathSessionResult(session_uuid=o.session_uuid, status=o.status, detail=o.detail) for o in report.outcomes])

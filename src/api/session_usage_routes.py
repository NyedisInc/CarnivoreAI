
from __future__ import annotations

from typing import Dict, Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.core.session_usage import rollup

router = APIRouter(tags=["session-usage"], dependencies=[Depends(require_auth)])


class SessionUsage(BaseModel):
    """One session's worked time in the window."""

    worked_s: float = Field(description="seconds the session's conversations were in the working state")
    active_days: int = Field(description="distinct local days with any work")
    last_worked_at: Optional[str] = Field(None, description="UTC time of the newest worked minute; null when none was worked")


class SessionUsageAnswer(BaseModel):
    """The rollup. ``by_session`` holds only sessions with an activity row in the window."""

    state: Literal["ok", "no_stats", "no_sessions", "unreadable"]
    days: int
    measured_since: Optional[str] = Field(None, description="UTC time of the oldest activity row the stats store holds")
    by_session: Dict[str, SessionUsage] = Field(default_factory=dict)


@router.get("/sessions/usage", response_model=SessionUsageAnswer)
async def sessions_usage(days: int = Query(rollup.DEFAULT_DAYS, ge=rollup.MIN_DAYS, le=rollup.MAX_DAYS)) -> SessionUsageAnswer:
    """Worked seconds, active days and last worked time per session over the last ``days`` days (1 to 90, default 30).

    Inputs: days. Output: SessionUsageAnswer. Never an error for missing data: ``state`` says what was not measured.
    Example: GET /api/v1/sessions/usage?days=30
    """
    return SessionUsageAnswer(**await run_in_threadpool(rollup.build, days))

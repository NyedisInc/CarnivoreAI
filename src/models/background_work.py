
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

BackgroundWorkState = Literal["ok", "absent", "unchecked", "not_applicable"]

TerminateOutcome = Literal["terminated", "killed", "still_running", "already_gone"]

TargetOutcomeName = Literal["terminated", "killed", "still_running", "already_gone", "refused"]

OwnersState = Literal["ok", "absent", "unchecked"]

MAX_BATCH_TARGETS: int = 20


class BackgroundProcess(BaseModel):
    """One of the agent's tool shells, with what the stop route needs back."""

    pid: int
    start: str
    task_id: Optional[str] = None
    started_at: Optional[str] = None
    children: int = 0
    summary: Optional[str] = None
    agent_id: Optional[str] = None


class SessionBackgroundWork(BaseModel):
    """``GET /api/v1/sessions/{id}/background-work``."""

    state: BackgroundWorkState
    family: Optional[str] = None
    processes: List[BackgroundProcess] = Field(default_factory=list)
    owners: OwnersState = "unchecked"
    detail: str = ""
    as_of: Optional[str] = None


class TerminateRequest(BaseModel):
    """``POST .../background-work/{pid}/terminate``'s body."""

    start: str = Field(min_length=1, max_length=64)


class TerminateResponse(BaseModel):
    """What stopping one process did."""

    pid: int
    outcome: TerminateOutcome
    term: List[int] = Field(default_factory=list)
    kill: List[int] = Field(default_factory=list)
    survivors: List[int] = Field(default_factory=list)
    detail: str = ""


class TerminateTarget(BaseModel):
    """One process a batch stop names, as the listing returned it."""

    pid: int
    start: str = Field(min_length=1, max_length=64)


class TerminateAllRequest(BaseModel):
    """``POST .../background-work/terminate-all``'s body (issue #1053).

    The pairs the user was shown and confirmed; a process not named here is
    never stopped, whatever else runs.
    """

    targets: List[TerminateTarget] = Field(min_length=1, max_length=MAX_BATCH_TARGETS)


class TargetResult(BaseModel):
    """What a batch stop did to one target."""

    pid: int
    outcome: TargetOutcomeName
    code: Optional[str] = None
    detail: str = ""


class TerminateAllResponse(BaseModel):
    """What a batch stop did, per target and in total."""

    results: List[TargetResult] = Field(default_factory=list)
    term: List[int] = Field(default_factory=list)
    kill: List[int] = Field(default_factory=list)
    survivors: List[int] = Field(default_factory=list)


class InterruptRequest(BaseModel):
    """``POST /api/v1/sessions/{id}/interrupt``'s body (issue #1053).

    ``confirm`` must be true: the UI arms, then confirms, and a request
    without the confirmation is refused before anything is measured.
    """

    confirm: Literal[True]


class InterruptResponse(BaseModel):
    """What the interrupt sent."""

    sent: bool
    key: Literal["escape"] = "escape"
    agent_pid: int
    activity_status: Optional[str] = None
    detail: str = ""

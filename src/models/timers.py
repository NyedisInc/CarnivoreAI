
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

TimersState = Literal["ok", "absent", "unchecked", "not_applicable"]

TimerKind = Literal["wakeup", "cron", "sleep"]

TimerStatus = Literal[
    "live",
    "fired",
    "cancelled",
    "superseded",
    "expired",
    "lost",
    "refused",
    "unknown",  # could not
    "shape_unrecognized",
]

ProcessState = Literal["alive", "gone", "unknown"]


class TimerInfo(BaseModel):
    """One timer the current conversation set."""

    id: str
    kind: TimerKind
    status: TimerStatus
    cron: Optional[str] = None
    human_schedule: Optional[str] = None
    delay_seconds: Optional[int] = None
    recurring: Optional[bool] = None
    durable: Optional[bool] = None
    created_at: str
    fire_at: Optional[str] = None
    expires_at: Optional[str] = None
    prompt: Optional[str] = None
    reason: Optional[str] = None


class TimerCounts(BaseModel):
    """Counts over every timer the conversation recorded."""

    total: int
    live: int
    fired: int
    cancelled: int
    superseded: int
    expired: int
    lost: int
    refused: int
    unknown: int
    shape_unrecognized: int


class ParkedEntry(BaseModel):
    """One sub-agent's own open background shell or Monitor (issue #945
    follow-up, #1039), from ``src.core.subagents.parked_work.ParkedEntry``.

    A REAL LIST, unlike ``BackgroundTasks.open`` below: these come from
    ``evidence.parked_work``, discrete launch records, never a tail-window
    floor. NEVER a command or output: ``summary`` is the ready-to-show
    sentence (task id, owning sub-agent, kind, age), already redacted.
    """

    task_id: str
    kind: Literal["shell", "monitor"]
    agent_id: str
    live: bool
    started_at: Optional[str] = None
    summary: str


class BackgroundTasks(BaseModel):
    """Background shells and monitors, as the watcher already counts them.

    COUNTS ONLY for ``open``/``detail``: the watcher's ledger
    (``transcript_facts``) counts open launches in a bounded tail window,
    so that pair is a FLOOR, not a list. ``open`` is None when no fresh
    observation exists. ``parked`` is a SEPARATE, real list (see
    :class:`ParkedEntry`).
    """

    open: Optional[int] = None
    detail: str
    parked: List[ParkedEntry] = []


class SessionTimers(BaseModel):
    """``GET /sessions/{id}/timers``."""

    state: TimersState
    family: Optional[str] = None
    conversation_uuid: Optional[str] = None
    process: ProcessState = "unknown"
    process_started_at: Optional[str] = None
    counts: Optional[TimerCounts] = None
    next_fire_at: Optional[str] = None
    timers: List[TimerInfo] = []
    background: Optional[BackgroundTasks] = None
    contract_versions: Dict[str, int] = {}
    detail: str = ""
    as_of: Optional[str] = None

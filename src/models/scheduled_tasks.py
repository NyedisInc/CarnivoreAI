"""App-level scheduled tasks, as ``GET /scheduled-tasks`` answers (issue #893).

NOTHING GUESSED ON THE WIRE. ``schedule`` is only ever what the task's
own frontmatter records (``schedule_source: frontmatter``); otherwise it
is null with ``schedule_source: not_recorded``, and ``next_run_at`` is
null because nothing on disk here records one. ``last_run_at`` and
``runs_recorded`` come from the scheduler's own enqueue record at the head
of each run's transcript. Text is redacted and truncated. No path.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel

ScheduledTasksState = Literal["ok", "absent", "unreadable"]

TaskFileState = Literal["ok", "missing", "too_large", "unreadable", "no_frontmatter"]


class ScheduledTask(BaseModel):
    """One ``~/.claude/scheduled-tasks/<id>/SKILL.md``."""

    id: str
    name: str
    description: Optional[str] = None
    file_state: TaskFileState
    schedule: Optional[str] = None
    schedule_source: Literal["frontmatter", "not_recorded"] = "not_recorded"
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    runs_recorded: int = 0
    updated_at: Optional[str] = None
    host_key: Optional[str] = None
    host_label: Optional[str] = None


class PeerTasksState(BaseModel):
    """How reading one paired Mac's list went; a Mac that did not answer is named, never silently empty."""

    host_key: str
    host_label: str
    state: Literal["ok", "peer_unavailable"]
    total: int = 0


class ScheduledTasksList(BaseModel):
    """``GET /api/v1/scheduled-tasks``."""

    state: ScheduledTasksState
    tasks: List[ScheduledTask] = []
    total: int = 0
    truncated: bool = False
    runs_truncated: bool = False
    detail: str = ""
    as_of: Optional[str] = None
    peers: List[PeerTasksState] = []


from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

TaskStatus = Literal["pending", "in_progress", "completed"]
TasksState = Literal["ok", "empty", "unknown", "unsupported", "remote"]


class TaskItem(BaseModel):
    """One task on the agent's list."""

    id: str
    subject: str = Field(description="the task text, redacted and capped")
    active_form: Optional[str] = Field(default=None, description="the present-tense line shown while it runs")
    status: TaskStatus


class TaskCounts(BaseModel):
    """How many tasks sit in each state."""

    pending: int = 0
    in_progress: int = 0
    completed: int = 0


class SessionTasks(BaseModel):
    """One session's task list."""

    state: TasksState
    session_id: Optional[str] = None
    label: Optional[str] = Field(default=None, description="the session's display name (global view)")
    tasks: List[TaskItem] = Field(default_factory=list)
    counts: TaskCounts = Field(default_factory=TaskCounts)


class AllSessionTasks(BaseModel):
    """Every live session that has a task list, one entry each (sessions with none are left out)."""

    sessions: List[SessionTasks] = Field(default_factory=list)

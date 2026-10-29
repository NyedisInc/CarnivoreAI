
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

SubagentsState = Literal["ok", "absent", "unchecked", "not_applicable"]

SubagentStatus = Literal["running", "done", "unknown"]

SubagentStatusReason = Literal[
    "end_recorded",
    "no_end_recorded",
    "resumed_after_end",
    "process_restarted",
    "silent",
    "parent_unreadable",
    "shape_unrecognized",
    "transcript_unreadable",
]

FileShape = Literal["ok", "absent", "unreadable", "shape_unrecognized"]


class SubagentInfo(BaseModel):
    """One subagent of the session's current conversation."""

    id: str
    agent_type: Optional[str] = None
    description: Optional[str] = None
    model: Optional[str] = None
    background: Optional[bool] = None
    spawn_depth: Optional[int] = None
    started_at: Optional[str] = None
    last_activity_at: Optional[str] = None
    status: SubagentStatus
    status_reason: SubagentStatusReason
    end_status: Optional[str] = None
    meta_shape: FileShape
    transcript_shape: FileShape


class SubagentCounts(BaseModel):
    """Counts over every subagent file of the current conversation."""

    total: int
    listed: int
    running: int
    done: int
    unknown: int
    shape_unrecognized: int
    internal: int


class SessionSubagents(BaseModel):
    """The response of ``GET /api/v1/sessions/{session_id}/subagents``."""

    state: SubagentsState
    family: Optional[str] = None
    conversation_uuid: Optional[str] = None
    counts: Optional[SubagentCounts] = None
    subagents: List[SubagentInfo] = Field(default_factory=list)
    contract_versions: Dict[str, int] = Field(default_factory=dict)
    detail: str = ""
    as_of: Optional[str] = None

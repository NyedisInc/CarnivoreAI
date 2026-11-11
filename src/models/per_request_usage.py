
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel

PerRequestState = Literal["ok", "absent", "unchecked", "not_applicable"]


class RequestUsageRow(BaseModel):
    """One model request: who made it, on what model, and its four disjoint token classes."""

    request_id: Optional[str] = None
    message_id: Optional[str] = None
    agent_id: str
    workflow: Optional[str] = None
    model: Optional[str] = None
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    timestamp: Optional[str] = None


class SessionRequestUsage(BaseModel):
    """The per-request usage of one session's current conversation."""

    state: PerRequestState
    family: Optional[str] = None
    conversation_uuid: Optional[str] = None
    as_of: Optional[str] = None
    requests: List[RequestUsageRow] = []
    total: Optional[int] = None
    truncated: bool = False
    next_since: Optional[str] = None
    detail: Optional[str] = None

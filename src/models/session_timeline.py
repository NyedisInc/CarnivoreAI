
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class TimelineSplit(BaseModel):
    """Where a fork, branch or rewind was cut: the conversation and message it split from."""

    conversation: Optional[str] = None
    message_uuid: Optional[str] = None
    line: Optional[int] = None
    at: Optional[str] = Field(None, description="when that message was written (ISO), when its transcript could be read")


class TimelineBegan(BaseModel):
    """How a conversation began."""

    kind: str = Field(description="clear, fork, rewind, resume, switch or compact_continue")
    from_conversation: Optional[str] = None
    basis: Optional[str] = None
    at: Optional[str] = None
    split: Optional[TimelineSplit] = None


class TimelineActivity(BaseModel):
    """One run of a bar's busy and idle band, from the stats plugin's per-minute activity (``session_timeline/activity.py``)."""

    state: str = Field(description="busy (it did work in the run) or idle (observed, no work)")
    start: str = Field(description="ISO")
    end: str = Field(description="ISO")
    busy_seconds: float = Field(0, description="seconds worked inside the run; 0 for idle")


class TimelineBar(BaseModel):
    """One conversation as a bar: the span it covers, oldest bar first."""

    conversation_id: str
    current: bool
    level: Optional[str] = None
    began: Optional[TimelineBegan] = None
    started_at: Optional[str] = Field(None, description="ISO; the edge that began it, else its first recorded moment")
    ended_at: Optional[str] = Field(None, description="ISO; when the session left it, else now for the current bar")
    activity: Optional[List[TimelineActivity]] = Field(
        None, description="busy and idle runs oldest first, clipped to the bar; null when the stats never measured it")
    busy_seconds: Optional[float] = Field(None, description="seconds worked inside the bar's span; null when unmeasured")


class TimelineMark(BaseModel):
    """One moment on a bar."""

    id: str = Field(description="stable within the answer: kind plus the source's own id")
    kind: str = Field(description="compact, bookmark, restart or restore")
    conversation_id: str
    at: Optional[str] = None
    entry_uuid: Optional[str] = Field(None, description="the transcript record it sits at; branch, rewind, bookmark and peek need it")
    label: str = ""
    snippet: str = ""
    can_peek: bool = False
    trigger: Optional[str] = None
    pre_tokens: Optional[int] = Field(None, description="compact: the context it dropped, when claude recorded it")
    bookmark_id: Optional[int] = None
    created_by: Optional[str] = None
    point_id: Optional[str] = None
    reason: Optional[str] = None
    pinned: Optional[bool] = None
    failsafe: Optional[bool] = Field(None, description="restore: the one rotating just-in-case copy")
    turns: Optional[int] = None


class TimelineGap(BaseModel):
    """A stretch the session spent asleep, from the sleep to the first sign it woke."""

    id: str
    conversation_id: str
    start: str
    end: Optional[str] = Field(None, description="ISO; null while still asleep")
    open: bool = False


class TimelineAttention(BaseModel):
    """One waiting or done stretch of the session, from the watcher's own confirmed edges (history starts on the ship date)."""

    kind: str = Field(description="question, notice, startup or done")
    start: str
    end: Optional[str] = Field(None, description="ISO; null while it is the session's newest state")


class SessionTimeline(BaseModel):
    """A session's timeline: bars (conversations), the marks on them and the sleep gaps."""

    session_uuid: str
    session_row_id: int
    family: str
    current_conversation: Optional[str] = None
    now: str
    bars: List[TimelineBar] = Field(default_factory=list)
    marks: List[TimelineMark] = Field(default_factory=list)
    gaps: List[TimelineGap] = Field(default_factory=list)
    attention: List[TimelineAttention] = Field(
        default_factory=list, description="waiting and done stretches inside the timeline window, oldest first")


class PeekPart(BaseModel):
    """One chat message of a peek."""

    entry_uuid: str
    role: str
    text: str
    timestamp: Optional[str] = None
    truncated: bool = False


class TimelinePeek(BaseModel):
    """The chat messages around a point, oldest first, read only."""

    conversation: str
    entry_uuid: str
    turns: int
    parts: List[PeekPart] = Field(default_factory=list)

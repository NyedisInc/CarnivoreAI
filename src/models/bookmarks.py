
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class Bookmark(BaseModel):
    """One bookmark: a point in one Claude conversation of one session row."""

    id: int
    session_uuid: str
    session_row_id: Optional[int] = None
    claude_session_uuid: str = Field(description="The conversation the point is in (it may be an earlier one of this row).")
    entry_uuid: str = Field(description="The transcript record the point names.")
    label: str = ""
    created_by: Literal["owner", "claude"]
    created_at: str
    snippet: str = Field("", description="The text that opened the marked turn: a typed prompt or a peer agent's message.")
    entry_timestamp: str = ""


class SessionBookmark(Bookmark):

    session_label: str = Field("", description="The session's title, else its tmux name; empty when the row is gone.")
    session_tmux: str = ""
    family: str = Field("", description="The session's agent family; empty when the row is gone.")


class CompactionPoint(BaseModel):
    """An automatic bookmark at a /compact point, derived from the lineage's compact milestones (not stored)."""

    entry_uuid: Optional[str] = Field(None, description=(
        "The compact boundary record. Pass it to the point routes (branch / rewind); null when it cannot be named."))
    conversation: str
    at: str = Field("", description="When the compaction happened (ISO), as the transcript recorded it.")
    trigger: str = Field("", description="'manual' or 'auto', when claude recorded it.")
    pre_tokens: Optional[int] = None
    jsonl_line: Optional[int] = None


class SessionCompaction(CompactionPoint):

    session_uuid: str
    session_row_id: Optional[int] = None
    session_label: str = ""
    session_tmux: str = ""
    family: str = "claude"


class AllBookmarks(BaseModel):
    """The newest bookmarks across every session, newest first, and the newest compaction points of every Claude session."""

    bookmarks: List[SessionBookmark] = Field(default_factory=list)
    compactions: List[SessionCompaction] = Field(
        default_factory=list, description="Automatic bookmarks at /compact points across sessions, newest first (one batched read).")


class BookmarkList(BaseModel):
    """A session's bookmarks, newest first, and the conversation it is on now."""

    session_uuid: str
    conversation: Optional[str] = None
    family: str = Field(description="The agent family; only 'claude' sessions take bookmarks.")
    bookmarks: List[Bookmark] = Field(default_factory=list)
    compactions: List[CompactionPoint] = Field(
        default_factory=list, description="Automatic bookmarks at each /compact point of the current conversation, newest first.")


class AddBookmarkRequest(BaseModel):
    """Bookmark a point of the session's current conversation."""

    label: str = Field("", max_length=200)
    entry_uuid: Optional[str] = Field(None, description="A record from GET .../turns; omit to use `point`.")
    point: Literal["turn", "now"] = Field(
        "turn", description="With no entry_uuid: 'turn' marks the latest prompt's turn, 'now' the newest record.")
    created_by: Literal["owner", "claude"] = "owner"


class Turn(BaseModel):
    """One human prompt of the conversation."""

    entry_uuid: str
    snippet: str
    timestamp: str
    number: int = Field(description="1 is the conversation's first prompt.")


class TurnPage(BaseModel):
    """One page of a session's past turns, newest first."""

    session_uuid: str
    conversation: str
    total: int
    turns: List[Turn] = Field(default_factory=list)


class PreviewPart(BaseModel):
    """One chat message of a bookmark's preview: a prompt or an assistant reply."""

    entry_uuid: str
    role: Literal["user", "assistant"]
    text: str
    timestamp: str = ""
    truncated: bool = Field(False, description="The text was cut to the preview's per-message limit.")


class BookmarkPreview(BaseModel):
    """The last few chat messages up to a bookmark's point, oldest first."""

    bookmark_id: int
    conversation: str
    turns: int = Field(description="N, the number of messages asked for (the bookmarks widget's previewTurns setting by default).")
    parts: List[PreviewPart] = Field(default_factory=list)


class CompactionPreview(BaseModel):
    """The last few chat messages before a compaction point (its boundary record), oldest first."""

    entry_uuid: str
    conversation: str
    turns: int = Field(description="N, the number of messages asked for (the bookmarks widget's previewTurns setting by default).")
    parts: List[PreviewPart] = Field(default_factory=list)


class PointRequest(BaseModel):
    """A point to act on without a stored bookmark: a turn from the past-turns list."""

    entry_uuid: str = Field(min_length=1, max_length=64)
    conversation: Optional[str] = Field(None, max_length=64, description="The entry's conversation; the current one by default.")


class RewindPointRequest(PointRequest):

    confirm: bool = Field(False, description=(
        "Replace what is RUNNING: kills the pane's process and resumes it on the cut copy (respawn-pane -k). "
        "Must be an explicit act by the user; false is refused."))


class ConfirmRequest(BaseModel):
    """A rewind of a stored bookmark; ``confirm`` is the ticked arm box."""

    confirm: bool = Field(False, description="As RewindPointRequest.confirm.")


class BranchResponse(BaseModel):
    """A new session opened on a cut copy."""

    session: dict = Field(default_factory=dict)
    claude_session_uuid: str
    label: str
    parent_session_id: int
    lineage_recorded: bool
    split_recorded: bool = Field(False, description="The cut (source conversation, message) is in the lineage graph.")


class RewindResponse(BaseModel):
    """This session restarted on a cut copy. The previous conversation is still on disk."""

    claude_session_uuid: str
    previous_claude_session_uuid: str
    killed_live_pane: bool
    resumed_copy: bool = Field(description="The command that ran carried the copy's uuid.")
    identity_status: Optional[str] = None
    kind: Optional[str] = None
    ok: bool
    detail: Optional[str] = None
    lineage_recorded: bool = Field(False, description="The rewind edge, milestone and split point are in the lineage graph.")

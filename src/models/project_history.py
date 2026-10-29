
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class HistorySession(BaseModel):
    """One stored session row, as the projects page draws it."""

    session_uuid: str = Field(..., description="The row key, stable across rename, kill and restart")
    row_id: Optional[int] = Field(None, description="sessions.id, the key a terminal tab is stored under")
    title: str = Field(..., description="The label, else claude's title, else the tmux name")
    label: Optional[str] = Field(None, description="The user's own label (sessions.title), or null")
    tmux_name: Optional[str] = None
    host_key: str = Field("local", description="The machine the session ran on")
    host_label: Optional[str] = Field(None, description="That machine's label; set on a paired computer's sessions (#163, P8)")
    state: str = Field(..., description="running, asleep, closed, removed or unknown")
    lifecycle: Optional[str] = None
    lifecycle_source: Optional[str] = None
    archived_at: Optional[str] = Field(None, description="Set when the row was removed from the lists")
    agent_type: Optional[str] = None
    agent_family: Optional[str] = Field(None, description="Display family; null is unknown, never a guess")
    claude_session_uuid: Optional[str] = Field(None, description="The conversation a resume would continue")
    has_transcript: bool = Field(
        False,
        description=(
            "True when ~/.claude/projects holds this conversation's transcript, "
            "so a restart resumes it. False with a conversation id means the "
            "transcript is gone from the live corpus; only the archive plugin "
            "(issue #800) could still show it."
        ),
    )
    created_at: Optional[str] = None
    last_seen_running_at: Optional[str] = None
    last_work_at: Optional[str] = None
    last_activity_at: Optional[str] = Field(None, description="Newest of work, seen running and created")
    working_dir: Optional[str] = None
    origin: Optional[str] = None
    kind: Optional[str] = None
    fork_kind: Optional[str] = None
    live_session_id: Optional[str] = Field(
        None, description="The app session id holding a running row's pane, when this server holds one"
    )


class HistoryProject(BaseModel):
    """One project, as the page's group header draws it."""

    id: Optional[int] = None
    name: str
    root: Optional[str] = None
    description: Optional[str] = None
    archived_at: Optional[str] = None
    last_opened_at: Optional[str] = None
    created_at: Optional[str] = None
    default_theme: Optional[str] = Field(None, description="The folder's .cc.theme, read only")
    company_id: Optional[int] = Field(None, description="The company this project is filed under, null when orphaned")
    company_name: Optional[str] = Field(None, description="That company's name, null when orphaned")
    has_image: bool = Field(False, description="An uploaded hero image is stored for this project")
    image_rev: Optional[str] = Field(None, description="Changes on every re-upload; the client sends it as ?rev=")
    storage: Optional[Dict[str, Any]] = Field(
        None, description="The pack state of the folder (docs/project-pack.md); null when it was never packed")
    pack_state: Optional[str] = Field(None, description="home, replica or moved_away (P2); null before schema v80")
    moved_to_label: Optional[str] = Field(None, description="The machine a moved-away project went to, for the words moved to <machine>")


class HistoryGroup(BaseModel):
    """A project and its matching sessions. ``project`` null is the no-project group."""

    key: str = Field(..., description="The project id, or 'none'; pass it back as ?project= for the rest")
    project: Optional[HistoryProject] = None
    session_total: int = Field(..., description="Matching sessions in this group, not only the ones returned")
    counts: Dict[str, int] = Field(default_factory=dict, description="Matching sessions per state")
    automated_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Of the matching sessions, how many are automated runs, per state (a subset of counts)",
    )
    activity_days: List[int] = Field(
        default_factory=list,
        description=(
            "Sessions active on each of the last 14 UTC days, oldest first, today last; a day counts only "
            "where a stored instant (created, last work, last seen running) falls on it, plus every day up "
            "to today for a session that is running or asleep"
        ),
    )
    last_activity_at: Optional[str] = None
    sessions: List[HistorySession] = Field(default_factory=list)
    host_key: str = Field("local", description="The machine this group came from; a paired computer's key on a peer group")
    host_label: Optional[str] = None


class HistoryFacets(BaseModel):
    """What the filter controls can offer."""

    agents: List[str] = Field(default_factory=list, description="Every family present, 'unknown' included")
    states: Dict[str, int] = Field(
        default_factory=dict, description="Per-state counts over rows passing every filter but state"
    )


class PeerUnavailable(BaseModel):
    """A paired Mac that could not answer this request (#163, P8): named, never an error."""

    host_key: str
    host_label: str
    reason: str


class ProjectHistoryResponse(BaseModel):
    """One page of the projects page's history."""

    state: str = Field(
        ..., description="ok, or no_datastore (nothing could be read; never rendered as 'no projects')"
    )
    total: int = 0
    offset: int = 0
    limit: int = 0
    next_offset: Optional[int] = Field(None, description="The offset of the next page, null at the end")
    groups: List[HistoryGroup] = Field(default_factory=list)
    facets: HistoryFacets = Field(default_factory=HistoryFacets)
    peer_groups: List[HistoryGroup] = Field(
        default_factory=list,
        description="Paired computers' groups fetched at request time (first page only), each session tagged with its machine",
    )
    peer_unavailable: List[PeerUnavailable] = Field(
        default_factory=list, description="Paired computers that did not answer; the local groups are complete without them"
    )

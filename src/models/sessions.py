
from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.hosts.ddl import HOST_STATE_UP, LOCAL_HOST_KEY, LOCAL_HOST_LABEL
from src.models.auto_sleep import SleepHoldInfo
from src.models.utc_time import as_aware_utc, utc_now


class SessionStatus(str, Enum):
    CREATING = "creating"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


class LocalServerInfo(BaseModel):
    """A dev-server port detected on the host, surfaced to the UI."""
    port: int = Field(..., description="TCP port the server is bound to (1024-65535)")
    url: str = Field(..., description="Clickable URL the web client should render")
    first_seen: datetime = Field(default_factory=utc_now)
    last_seen: datetime = Field(default_factory=utc_now)

    @field_validator("first_seen", "last_seen", mode="after")
    @classmethod
    def _stamps_are_aware_utc(cls, value: datetime) -> datetime:
        return as_aware_utc(value)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class Session(BaseModel):
    """Session model for Claude Code instance.

    Phase 6 - ``agent_type`` labels which agent CLI was launched in this
    session ("claude" / "codex" / "hermes" / "openclaw"). Optional + None
    default so legacy ``session_metadata.json`` files (written before the
    field existed) deserialize cleanly. The lifespan startup backfill in
    ``SessionManager.lifespan_startup`` populates None-valued agent_type
    on owned sessions to ``"claude"`` (the only agent type pre-Phase-6
    sessions could have been). Adopted sessions stay None until Phase 7
    fingerprint detection back-fills them.
    """
    id: str = Field(..., description="Unique session identifier")
    pty_pid: Optional[int] = Field(None, description="PTY process PID")
    working_dir: str = Field(..., description="Working directory path")
    status: SessionStatus = SessionStatus.CREATING
    created_at: datetime = Field(default_factory=utc_now)
    last_activity: datetime = Field(default_factory=utc_now)
    agent_type: Optional[str] = Field(
        None,
        description="Agent CLI type: 'claude' | 'codex' | 'hermes' | 'openclaw' (None = unknown / pre-Phase-6 / not yet fingerprinted)",
    )
    agent_type_via_fingerprint: bool = Field(
        default=False,
        description="True iff agent_type came from scrollback fingerprinting, not an explicit choice",
    )
    pinned_theme: Optional[str] = Field(
        None,
        description="Theme id pinned to this session; None = follow global theme",
    )
    tmux_session: Optional[str] = Field(
        None,
        description="Bare tmux session name (canonical pin-key handle)",
    )
    tmux_created_epoch: Optional[int] = Field(
        None,
        description="tmux #{session_created} of this instance; None = unmeasured",
    )
    model: Optional[str] = Field(
        None,
        description="OpenRouter model id this session was launched with (None = Claude direct via 'cld')",
    )

    @field_validator("created_at", "last_activity", mode="after")
    @classmethod
    def _stamps_are_aware_utc(cls, value: datetime) -> datetime:
        return as_aware_utc(value)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class LogEntry(BaseModel):
    """Log entry model for terminal output."""
    timestamp: datetime = Field(default_factory=utc_now)
    session_id: str
    content: str
    log_type: str = "stdout"

    @field_validator("timestamp", mode="after")
    @classmethod
    def _stamps_are_aware_utc(cls, value: datetime) -> datetime:
        return as_aware_utc(value)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class SessionStats(BaseModel):
    """Session statistics."""
    total_commands: int = 0
    uptime_seconds: int = 0
    log_lines: int = 0
    local_servers: int = 0


class AgentUpdateInfo(BaseModel):
    """A row's measured update-ready fact (issue #1061), or the field is null.

    Mirrors ``src.core.sessions.agent_update.AgentUpdate`` field for field; never
    built from anything else, so this shape and that dataclass cannot
    drift. ``ready`` is only ever True when both versions parsed AND
    ``running`` sorts strictly before ``installed`` - a dev build or a
    rollback (running newer than installed) answers False, not True.
    """
    running: str = Field(description="Version this session's claude process is executing")
    installed: str = Field(description="Newest version installed on this computer")
    ready: bool = Field(description="True only when running is strictly older than installed")


class McpDropInfo(BaseModel):
    """One MCP server that is not connected, in the original shape (docs/session-status.md, "MCP drops")."""
    name: str = Field(description="Server name; the exact config name when `exact`")
    state: Literal["dropped", "failed", "needs_auth"] = Field(description="Why it is not connected")
    at: Optional[str] = Field(default=None, description="ISO 8601 UTC time of the evidence saying so")
    exact: bool = Field(description="True when `name` can be handed to `/mcp reconnect <name>` as is")
    source: Literal["transcript", "server", "client_log", "process", "probe"] = Field(
        default="transcript",
        description=("Who said so: the transcript, this server's own first-hand record (carnivore), the session's "
                     "MCP client log, the stdio process tree, or Carnivore's reachability probe"),
    )


class McpServerHealthInfo(BaseModel):
    """One MCP server of a session with its measured state (#1678; docs/session-status.md, "MCP servers")."""
    name: str = Field(description="Server name; the exact config name when `exact`")
    transport: Literal["stdio", "http", "sse", "proxy", "unknown"] = Field(description="How the agent reaches it")
    state: Literal["connected", "down", "needs_auth", "unknown"] = Field(
        description="connected, down, needs_auth, or unknown (not measurable, or the link is not visible)"
    )
    reason: str = Field(description="Stable reason code; the catalog renders mcp.reason.<code>")
    source: Literal["first_hand", "client_log", "process", "probe", "transcript"] = Field(
        description="The evidence that decided the state"
    )
    detail: Optional[str] = Field(default=None, description="Short measured qualifier: an error code or HTTP status")
    at: Optional[str] = Field(default=None, description="ISO 8601 UTC time of the deciding evidence")
    exact: bool = Field(default=True, description="True when `name` can be handed to `/mcp reconnect <name>` as is")


class CarnivoreLinkInfo(BaseModel):
    """What THIS server process saw of a session's carnivore MCP client (docs/mcp-server.md, "Per-session link state")."""
    state: Literal["connected", "dropped", "unknown"] = Field(description="The link's first-hand state")
    initialized_at: Optional[str] = Field(default=None, description="ISO 8601 UTC time of its last initialize here")
    last_request_at: Optional[str] = Field(default=None, description="ISO 8601 UTC time of its last accepted request here")


class McpHealthInfo(BaseModel):
    """A session's MCP servers, measured, or the field is null (not measured).

    Mirrors ``src.core.mcp_health.fold.McpHealth``. ``servers`` is every configured or observed server with its
    state; ``dropped`` is its down and needs-auth subset in the original shape. An empty ``dropped`` is a MEASURED
    "nothing down"; null on the wrapper is "nothing measured", never "all well".
    """
    servers: List[McpServerHealthInfo] = Field(
        default_factory=list, description="Every server with its measured state, by name; empty before the first measure"
    )
    dropped: List[McpDropInfo] = Field(default_factory=list, description="Servers down or needing auth")
    carnivore: Optional[CarnivoreLinkInfo] = Field(
        default=None, description="This server's first-hand view of the session's carnivore link, when judged"
    )


class BackgroundProcessesInfo(BaseModel):
    """What the process tree says runs under a row's claude (issue #1185).

    Mirrors ``src.core.background_work.measured.BackgroundMeasure``: MEASURED
    on the watcher pass from the one ``ps`` snapshot, not read from a
    transcript flag. ``unknown`` is a real answer (the table or the claude
    pid could not be read), never idle, and its ``count`` is null, never 0.
    """
    state: Literal["running", "none", "unknown"] = Field(
        description="running, none, or unknown when it could not be measured"
    )
    count: Optional[int] = Field(
        default=None,
        description="Claude Code tool shells running under claude; null when unknown",
    )


class UsageLimitInfo(BaseModel):
    """A usage-limit hit the harness recorded (issue #1902). ON THE WRAPPER."""

    kind: Literal["session", "weekly", "weekly_model", "other"] = Field(
        description="session (5-hour), weekly, weekly_model (a per-model weekly cap) or other."
    )
    resets_at: Optional[str] = Field(
        default=None, description="ISO 8601 with UTC offset, or null when the record carries no reset time."
    )
    message: str = Field(description="The harness's own one-line limit text.")
    since: Optional[str] = Field(default=None, description="ISO 8601 with UTC offset: when the hit was recorded.")


class SkillLast(BaseModel):
    """The newest skill use of a session: its name and when (ISO 8601, or null)."""

    name: str
    at: Optional[str] = None


class AutomationMark(BaseModel):
    """The automation run that started a session (the sidebar's "auto" chip)."""

    automation_id: str
    run_id: str
    name: str


class ScheduledMark(BaseModel):
    """One scheduled thing counted in a session's Carnivore timers icon (an automation, or a plugin's scheduled item)."""

    name: str
    enabled: bool
    next_fire_at: Optional[float] = None


class MessagingMark(BaseModel):
    """This session's messaging bindings (issue #1499): the directions it is bound in and its held count."""

    directions: List[str] = Field(..., description="'in' and/or 'out', the union over its bindings")
    held: int = Field(..., description="Inbound texts held for this session (a dialog open, asleep, not running)")


class SessionInfo(BaseModel):
    """Complete session information including logs and detected local servers."""
    session: Session
    claude_title: Optional[str] = None
    recent_logs: List[LogEntry] = Field(default_factory=list)
    local_servers: List[LocalServerInfo] = Field(default_factory=list)
    stats: Optional[SessionStats] = Field(default_factory=SessionStats)
    session_backend: str = Field(
        default="none",
        description="Backend type driving this session: 'tmux', 'pty', or 'none'",
    )
    tmux_session: Optional[str] = Field(
        default=None,
        description="tmux session name (tmux backend only; None otherwise)",
    )
    session_row_id: Optional[int] = Field(
        None,
        description="sessions.id for this instance; None when we have no row",
    )
    parent_session_id: Optional[int] = Field(
        None,
        description="sessions.id this one was forked from; None = not a fork",
    )
    claude_session_uuid: Optional[str] = Field(
        None,
        description="Conversation id the session resumes; None = not known",
    )
    project_id: Optional[int] = Field(
        None,
        description="projects.id this session is bound to; None = unknown or none",
    )
    project_name: Optional[str] = Field(
        None,
        description="Display name of that project; None = unknown or none",
    )
    label: Optional[str] = Field(
        default=None,
        description=(
            "User-facing session label (sessions.title). Free-form; may "
            "contain spaces and punctuation. Falls back to tmux_session "
            "when None."
        ),
    )
    agent_type: Optional[str] = Field(
        default=None,
        description="Agent CLI type label (mirrors Session.agent_type)",
    )
    agent_family: Optional[str] = Field(
        default=None,
        description="Resolved family name for display ('claude'/'codex'/... ), or None if it could not be determined",
    )
    agent_family_source: Optional[str] = Field(
        default=None,
        description=(
            "Provenance of agent_family: 'wrapper' | 'reserved_name' | "
            "'fingerprint' | 'derived_deepest' | 'unknown'. See "
            "src.core.agent_families.resolve_family_for_display."
        ),
    )
    agent_wrapper_label: Optional[str] = Field(
        default=None,
        description="Configured label of the launch wrapper, or None if none can be named",
    )
    agent_wrapper_icon: Optional[str] = Field(
        default=None,
        description="Icon id of the launch profile, or None",
    )
    launched_with: Optional[dict] = Field(
        default=None,
        description="Launch profile label, account, model and permissions this session launched with, or None",
    )
    running_model: Optional[str] = Field(
        default=None,
        description="Model id the latest turn ran, e.g. 'claude-opus-5'. None = unknown.",
    )
    running_model_effort: Optional[str] = Field(
        default=None,
        description="Reasoning effort of the most recent turn. None = unknown.",
    )
    running_model_tier: Optional[int] = Field(
        default=None,
        description=(
            "Cost tier 1 (cheapest) to 5 for running_model, from "
            "cost_tier_for_model(). None when unknown or unpriced."
        ),
    )
    running_context_used_pct: Optional[float] = Field(
        default=None,
        description="Percent of the context window used by the last turn, 0-100. None = unknown.",
    )
    pinned_theme: Optional[str] = Field(
        default=None,
        description="Theme id pinned to this session (mirrors Session.pinned_theme)",
    )
    initial_scrollback_b64: Optional[str] = Field(
        default=None,
        description=(
            "Base64-encoded captured tmux scrollback bytes. Only populated "
            "when GET /sessions/{id}?include_scrollback=1, to support the "
            "launchpad rejoin path painting history before the WS opens."
        ),
    )
    activity_status: str = Field(
        default="unknown",
        description=(
            "Unified activity status: 'dead' | 'question' | 'notice' | "
            "'working' | 'working_subagent' | 'finished_unread' | 'idle' | "
            "'unknown'"
        ),
    )
    unread: bool = Field(
        default=False,
        description="True if this session has an unread Stop or a manual unread pin",
    )
    created_by_cloude: bool = Field(
        default=False,
        description=(
            "True iff this session is OURS - sessions.origin is 'created' "
            "or 'adopted'. False means 'observed': a session on our socket "
            "we have never claimed"
        ),
    )
    created_by_us: bool = Field(
        default=False,
        description=(
            "True iff this session is OURS. Same value as "
            "created_by_cloude, which is kept for the transition window "
            "(docs/rename-carnivore.md)."
        ),
    )
    startup_gate: str = Field(
        default="unknown",
        description=(
            "Startup-prompt gate: 'ready' | 'awaiting_startup_prompt' | "
            "'unknown'. See src.core.session_startup_gate."
        ),
    )
    notifications_muted: bool = Field(
        default=False,
        description=(
            "True when this session's stored row records that its "
            "notifications are muted. Defaults False, which is also what a "
            "session with no stored row reports"
        ),
    )

    status_source: str = Field(
        default="none",
        description=(
            "Provenance of activity_status: 'registry' | 'pane' | "
            "'transcript' | 'seed_row' | 'tmux' | 'none'. See "
            "src.core.session_status_source."
        ),
    )
    activity_hint: Optional[str] = Field(
        default=None,
        description=(
            "One extra fact about the session, rendered in the LED tooltip "
            "only: 'shell' when claude reports a shell command it started "
            "is still running. None when there is nothing to add."
        ),
    )
    spectator_expires_at: Optional[str] = Field(
        default=None,
        description=(
            "ISO 8601 UTC deadline of this session's live read-only share "
            "link, or null when it is not shared."
        ),
    )

    subagents_state: Optional[str] = Field(
        default=None,
        description=(
            "ok | absent | unchecked | not_applicable, or null when the "
            "watcher has not observed this session."
        ),
    )
    subagents_running: Optional[int] = Field(
        default=None,
        description="Subagents proven running; null when not measured.",
    )
    subagents_total: Optional[int] = Field(
        default=None,
        description=(
            "Every subagent the current conversation launched; null when not measured."
        ),
    )
    workflow_active: Optional[bool] = Field(
        default=None,
        description="True while a Workflow run is in flight; null when not measured.",
    )

    timers_state: Optional[str] = Field(
        default=None,
        description=(
            "ok | absent | unchecked | not_applicable, or null when the "
            "watcher has not observed this session."
        ),
    )
    timers_live: Optional[int] = Field(
        default=None,
        description="Timers proven live; null when not measured.",
    )
    timers_next_fire_at: Optional[str] = Field(
        default=None,
        description=(
            "ISO 8601 UTC instant the soonest live timer fires, or null."
        ),
    )
    automations_state: Optional[str] = Field(
        default=None,
        description="none | ok | warning | error | disabled, or null when not measured.",
    )
    automations_total: Optional[int] = Field(
        default=None, description="Automations aimed at this session; null when not measured.")
    automations_enabled: Optional[int] = Field(
        default=None, description="Those switched on; null when not measured.")
    automations_next: Optional[List[ScheduledMark]] = Field(
        default=None, description="The scheduled things counted in automations_total (name, next fire, on or off), soonest first, capped; null when not measured.")
    task_lead: Optional[bool] = Field(
        default=None, description="True on the project's task lead; false when measured and not; null when not measured.")
    do_not_disturb: Optional[bool] = Field(
        default=None, description="True when the session takes no new tasks; false when measured and not; null when not measured.")
    sleep_hold: Optional[SleepHoldInfo] = Field(
        default=None,
        description="Why auto-sleep will not touch this session (live work), or null.",
    )
    skills_state: Optional[str] = Field(
        default=None,
        description=(
            "measured | not_measured | unsupported, or null when the "
            "watcher has not observed this session."
        ),
    )
    skills_fired: Optional[int] = Field(
        default=None,
        description="Skill uses recorded in this conversation; null when not measured.",
    )
    skill_last: Optional[SkillLast] = Field(
        default=None,
        description="The newest skill use (name and time), or null when there is none.",
    )
    parked_summary: Optional[str] = Field(
        default=None,
        description=(
            "The reason working_subagent is true because of a parked "
            "sub-agent's own background work, or null."
        ),
    )
    account_id: Optional[str] = Field(
        default=None,
        description="Provider-ledger account id this session runs under, or null when not measured.",
    )
    automation: Optional[AutomationMark] = Field(
        default=None,
        description="The automation run that started this session, or null.",
    )
    messaging: Optional[MessagingMark] = Field(
        default=None,
        description="This session's messaging directions and held count, or null when not bound.",
    )
    short_description: Optional[str] = Field(
        default=None,
        description="This session's one-line description, or null when none is written.",
    )
    swarm_agent_id: Optional[int] = Field(default=None, description="The live Swarm agent whose body this session is, or null.")
    swarm_rank: Optional[str] = Field(default=None, description="That agent's rank (feature for a member), or null.")
    swarm_character_seed: Optional[int] = Field(default=None, description="That agent's character seed (its swarm sprite), or null.")
    swarm_color_slot: Optional[int] = Field(default=None, description="That agent's color slot 1 to 8, or null.")
    prompt_suggestion: Optional[str] = Field(
        default=None,
        description="The agent's suggested next prompt (its terminal's dim ghost text), or null.",
    )
    background_open: Optional[int] = Field(
        default=None,
        description=(
            "Open background shells and monitors of this session, or null "
            "when not measured."
        ),
    )
    background_processes: Optional[BackgroundProcessesInfo] = Field(
        default=None,
        description=(
            "Measured tool shells running under this session's claude "
            "(running/none/unknown), or null when not measured."
        ),
    )
    usage_limit: Optional[UsageLimitInfo] = Field(
        default=None,
        description="The recorded usage-limit hit (kind, resets_at, message, since), or null.",
    )
    agent_update: Optional[AgentUpdateInfo] = Field(
        default=None,
        description=(
            "running/installed/ready when measurable for this session's "
            "claude, else null."
        ),
    )
    mcp_health: Optional[McpHealthInfo] = Field(
        default=None,
        description="Every MCP server of the session with its measured state, else null (not measured).",
    )
    host_key: str = Field(
        default=LOCAL_HOST_KEY,
        description="hosts.key of the machine this session runs on; 'local' is this machine",
    )
    host_label: str = Field(
        default=LOCAL_HOST_LABEL,
        description="That host's display label",
    )
    host_state: str = Field(
        default=HOST_STATE_UP,
        description="That host's reachability; 'up' for this machine",
    )
    session_uuid: Optional[str] = Field(
        default=None, description="sessions.session_uuid; set only on a listing served to a peer")
    origin_install_id: Optional[str] = Field(
        default=None, description="install id of the computer that owns this row; set on a served or imported row")
    project_uid: Optional[str] = Field(default=None, description="projects.uid; set only on a listing served to a peer")
    company_uid: Optional[str] = Field(default=None, description="companies.uid; set only on a listing served to a peer")

    @model_validator(mode="after")
    def _mirror_created_by_us(self) -> "SessionInfo":
        self.created_by_us = self.created_by_cloude
        return self


class SkillFireOut(BaseModel):
    """One recorded skill use, as ``GET /sessions/{id}/skill-fires`` lists it."""

    skill: str
    at: Optional[str] = None
    source: str = Field(description="tool_use | slash | inferred (a codex SKILL.md read)")
    harness: str
    profile: str


class SessionSkillFires(BaseModel):
    """A session's skill fires: the count and the newest uses, newest first."""

    state: str = Field(description="measured | not_measured | unsupported")
    fired: Optional[int] = None
    recent: list[SkillFireOut] = Field(default_factory=list)


class SkillUsage(BaseModel):
    """One skill's local fire counts. Null counts mean not measured, never zero."""

    skill: str
    state: str = Field(description="measured | not_measured")
    fired_7d: Optional[int] = None
    fired_30d: Optional[int] = None
    fired_90d: Optional[int] = None

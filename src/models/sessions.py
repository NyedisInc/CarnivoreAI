
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
import structlog
from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.hosts.ddl import HOST_STATE_UP, LOCAL_HOST_KEY, LOCAL_HOST_LABEL
from src.models.activity_status import ActivityStatus, known_or_unknown
from src.models.auto_sleep import SleepHoldInfo, SleepVerdict
from src.models.mcp_health import McpHealthInfo
from src.models.session_marks import AutomationMark, CodexHelpersMark, MessagingMark, ScheduledMark, SkillLast
from src.models.utc_time import as_aware_utc, utc_now

logger = structlog.get_logger()

_UNRECOGNIZED_STATUS_SEEN_CAP: int = 64
_unrecognized_status_seen: set[str] = set()


def _warn_unrecognized_status_once(value: object) -> None:
    key = repr(value)
    if key in _unrecognized_status_seen or len(_unrecognized_status_seen) >= _UNRECOGNIZED_STATUS_SEEN_CAP:
        return
    _unrecognized_status_seen.add(key)
    logger.warning("activity_status_unrecognized", value=value)


class SessionStatus(str, Enum):
    CREATING = "creating"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


class LocalServerInfo(BaseModel):
    """A dev-server port detected on the host, surfaced to the UI."""
    port: int = Field(..., description="TCP port the server is bound to (1024-65535)")
    url: str = Field(..., description="Clickable URL the web client should render")
    address: Optional[str] = Field(None, description="Bind address (127.0.0.1, 0.0.0.0, ::1, ::); None = not measured")
    process: Optional[str] = Field(None, description="Short name of the program listening (node, python3.12); None = not measured")
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
    leftover: Optional[int] = Field(
        default=None,
        description=(
            "Of those shells, how many belong to a sub-agent that already finished "
            "(left behind, issue #2874); null when not measured, never a fake zero"
        ),
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


class LoginExpiredInfo(BaseModel):
    """A login lockout the harness recorded (issue #3013). ON THE WRAPPER."""

    message: str = Field(description="The harness's own one-line text, e.g. 'Login reached its time limit · Please run /login'.")
    since: Optional[str] = Field(default=None, description="ISO 8601 with UTC offset: when the newest lockout record was written.")


class SessionInfo(BaseModel):
    """Complete session information including logs and detected local servers."""
    session: Session
    claude_title: Optional[str] = None
    recent_logs: List[LogEntry] = Field(default_factory=list)
    local_servers: List[LocalServerInfo] = Field(default_factory=list)
    pr: Optional[Dict[str, Any]] = None
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
    activity_status: ActivityStatus = Field(
        default="unknown",
        description=(
            "Unified activity status: 'dead' | 'question' | 'notice' | "
            "'working' | 'working_subagent' | 'finished_unread' | 'idle' | "
            "'unknown'"
        ),
    )

    @field_validator("activity_status", mode="before")
    @classmethod
    def _unrecognized_status_is_unknown(cls, value: object) -> object:
        known = known_or_unknown(value)
        if known != value:
            _warn_unrecognized_status_once(value)
        return known

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
    subagents_stalled: Optional[int] = Field(
        default=None,
        description="Running subagents with no new transcript activity for the stall limit; null when not measured.",
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
    sleep_verdict: Optional[SleepVerdict] = Field(
        default=None, description="Why auto-sleep has not slept this session (last pass), or null.")
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
    stalled_agents: Optional[int] = Field(
        default=None,
        description="Sub-agents whose Monitor expired with no notice and no later activity, or null.",
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
    login_expired: Optional[LoginExpiredInfo] = Field(
        default=None,
        description="The recorded login lockout (message, since), or null.",
    )
    agent_update: Optional[AgentUpdateInfo] = Field(
        default=None,
        description=(
            "running/installed/ready when measurable for this session's "
            "claude, else null."
        ),
    )
    codex_helpers: Optional[CodexHelpersMark] = Field(
        default=None, description="The Codex helper check of this row's Codex version, else null (not measured).")
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
        default=None, description="sessions.session_uuid of this row; None when the session has no database row")
    origin_install_id: Optional[str] = Field(
        default=None, description="install id of the computer that owns this row; set on a served or imported row")
    project_uid: Optional[str] = Field(default=None, description="projects.uid; set only on a listing served to a peer")
    company_uid: Optional[str] = Field(default=None, description="companies.uid; set only on a listing served to a peer")
    parent_project_uid: Optional[str] = Field(
        default=None, description="parent project's projects.uid; set only on a listing served to a peer")
    last_work_at: Optional[str] = Field(
        default=None, description="sessions.last_work_at; set on a listing served to a peer")
    is_swarm: bool = Field(
        default=False, description="True when this peer-served row is a read-only Swarm agent summary.")
    swarm_role: Optional[str] = Field(
        default=None, description="Read-only Swarm agent rank/role summary ('alpha', 'company', 'project', 'feature', 'task'), or null.")
    hop: int = Field(
        default=0, description="Read-only relay hop count (0 = local or direct peer, 1 = relayed via one hub; never > 1).")
    origin_label: Optional[str] = Field(
        default=None, description="Originating computer display label for a relayed peer session, or null.")

    @model_validator(mode="after")
    def _mirror_created_by_us(self) -> "SessionInfo":
        self.created_by_us = self.created_by_cloude
        return self

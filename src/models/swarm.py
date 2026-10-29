
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.swarm.settings import LookAnimation, LookRank, LookShape, LookState

AgentState = Literal["asleep", "waking", "awake", "sleeping", "torn_down"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class SwarmOpenWake(BaseModel):
    """The agent's running wake: ``{"id": 4, "started_at": "...", "reason": "owner_message", "mode": "fresh"}``."""

    id: int
    started_at: str
    reason: Optional[str] = None
    mode: Optional[str] = None


class SwarmAgentSummary(BaseModel):
    """One agent in the roster. ``session_id`` and ``tmux_session`` are null while it is asleep."""

    id: int
    slug: str
    display_name: str
    rank: str
    state: AgentState
    parent_id: Optional[int] = None
    job: str
    repo_dir: str
    effort: str
    harness: str
    thread_key: str = Field(description="The agent's huddle list key: all, a project id, or agent:<id>")
    session_id: Optional[str] = Field(None, description="The body's current ses_ id; null while asleep")
    tmux_session: Optional[str] = Field(None, description="The body's tmux name; null while asleep")
    session_row_id: Optional[int] = Field(None, description="The agent's lifelong sessions row, asleep or awake; the clients' join key")
    session_uuid: Optional[str] = Field(None, description="That row's session_uuid, asleep or awake; null before its first wake")
    character_seed: Optional[int] = Field(None, description="Seeds the agent's look; an older row gets a stable derived value")
    color_slot: Optional[int] = Field(None, ge=1, le=8, description="Body color, --oc-series-N")
    color_chosen: bool = Field(False, description="color_slot was set by hand and wins; false: the body wears its company's color family")
    shape: Optional[LookShape] = Field(None, description="The node's own shape, beating its tier's (Swarm look); null: the tier default")
    tile_bg: Optional[int] = Field(None, ge=1, le=8, description="The node's tile background, --oc-series-N; null: none")
    host_key: str = Field("local", description="The computer the body runs on: 'local' is this one, else a paired computer's hosts.key")
    host_label: Optional[str] = Field(None, description="That paired computer's label; null for a local agent")
    placement_reason: Optional[str] = Field(None, description="Why the Pack placed this agent on its computer (pack_placements, the latest); null when none was recorded")
    project_id: Optional[int] = None
    company_id: Optional[int] = None
    persona: Optional[str] = None
    specialty: Optional[str] = Field(None, description="A feature agent's specialty, the domain new work of that kind is routed to; null for other ranks")
    alert: Optional[Literal["routine", "priority", "immediate", "flash"]] = Field(
        None, description="The highest open rung of the agent's thread, derived from its open cards (docs/swarm.md 13.2)")
    alert_reason: Optional[str] = Field(None, description="Short text for the rung, secrets starred")
    activity: Optional[Literal["talking", "escalating", "learning", "promoted", "done"]] = Field(
        None, description="The latest transient mark inside the last 8 seconds, else null")
    activity_at: Optional[float] = Field(None, description="Epoch seconds of the mark; the client shows it until this plus 8 s")
    talking_with: Optional[int] = Field(None, description="The peer agent id while activity is talking")
    question_waiting: bool = Field(False, description="The agent has a question of its own still open")


class SwarmAgentDetail(SwarmAgentSummary):

    goal: Optional[str] = None
    effort_reason: Optional[str] = None
    launch_profile: Optional[str] = None
    memory_scope: str
    children: List[int] = Field(default_factory=list, description="Ids of its live child agents")
    open_wake: Optional[SwarmOpenWake] = None


class SwarmLimits(BaseModel):
    """The optional body caps (null = no cap, the default) and how many bodies are live now."""

    max_children_per_parent: Optional[int] = None
    max_live_bodies: Optional[int] = None
    live_bodies: int


class SwarmRoster(BaseModel):
    """``GET /swarm/roster``: every live agent, oldest first, and the caps."""

    agents: List[SwarmAgentSummary]
    limits: SwarmLimits
    threads_ready: bool = Field(False, description="The huddle thread port is registered; false means the Swarm is inert (no SysOp, no cards)")


class SwarmLookRequest(BaseModel):
    """``PATCH /swarm/agents/{id}``: a node's own look, any subset of the fields. A field left out stays as it is; a field sent as
    null goes back to the automatic value (#1452). An empty body is refused (422)."""

    model_config = ConfigDict(extra="forbid")

    color_slot: Optional[int] = Field(None, ge=1, le=8, description="1 to 8: a hand-set body color that wins over the family; null: auto")
    shape: Optional[LookShape] = Field(None, description="One of the Swarm look's ten shapes, beating the tier's; null: the tier default")
    tile_bg: Optional[int] = Field(None, ge=1, le=8, description="1 to 8: a tile background, --oc-series-N; null: none")

    @model_validator(mode="after")
    def _not_empty(self) -> "SwarmLookRequest":
        if not self.model_fields_set:
            raise ValueError("name at least one of color_slot, shape, tile_bg")
        return self

    def updates(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if "color_slot" in self.model_fields_set:
            out.update({"color_slot": self.color_slot, "color_chosen": 1} if self.color_slot is not None else {"color_chosen": 0})
        for name in ("shape", "tile_bg"):
            if name in self.model_fields_set:
                out[name] = getattr(self, name)
        return out


class SwarmCreateRequest(BaseModel):
    """``POST /swarm/agents``: a new agent, created asleep (the first message or a wake starts its body).

    ``repo_dir`` is an absolute folder (``~`` allowed); it is made a git repo on the first wake when it is not one.
    ``rank`` is ``feature`` or ``task``; the project, company and Alpha agents come from their own routes.
    ``effort`` defaults to ``medium``; ``high`` and ``xhigh`` need ``effort_reason``; ``low`` and ``max`` are refused
    (``src/core/swarm/effort.py``, a 422 ``invalid_agent``).
    """

    model_config = ConfigDict(extra="forbid")

    repo_dir: str = Field(min_length=1, max_length=1024)
    job: str = Field(min_length=1, max_length=2000)
    display_name: Optional[str] = Field(None, min_length=1, max_length=80)
    rank: Literal["feature", "task"]
    parent_id: Optional[int] = Field(None, ge=1)
    goal: Optional[str] = Field(None, max_length=4000)
    effort: Optional[Effort] = None
    effort_reason: Optional[str] = Field(None, max_length=600)
    launch_profile: Optional[str] = Field(None, min_length=1, max_length=120)
    harness: Literal["claude", "codex"] = "claude"

    @field_validator("repo_dir", "job", "display_name")
    @classmethod
    def _not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        text = value.strip()
        if not text:
            raise ValueError("must not be blank")
        return text


class SwarmTurnOnRequest(BaseModel):
    """``POST /swarm/projects/{project_id}/agent``: turn on a project's agent (``launch_profile`` omitted: the Swarm default)."""

    model_config = ConfigDict(extra="forbid")

    launch_profile: Optional[str] = Field(None, min_length=1, max_length=120)


class SwarmPromoteRequest(BaseModel):
    """``POST /swarm/projects/{project_id}/promote``: the existing session (its durable ``session_uuid``) that becomes the project's agent."""

    model_config = ConfigDict(extra="forbid")

    session_uuid: str = Field(..., min_length=1, max_length=120)


class SwarmTurnOffRequest(BaseModel):
    """``POST /swarm/agents/{id}/turn-off``: ``confirm_name`` is the agent's exact display name, required for a company or project leader."""

    model_config = ConfigDict(extra="forbid")

    confirm_name: Optional[str] = Field(None, max_length=200)


class SwarmRenameRequest(BaseModel):
    """``PUT /swarm/agents/{id}/name``: the new display name of any live agent (the naming rules: 1 to 25 characters, no feat, fix
    or tweak first word, not another live agent's name in the same project; issue #1444)."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=200)


class SwarmWakeRequest(BaseModel):
    """``POST /swarm/agents/{id}/wake``: ``auto`` resumes only when there is open work, ``fresh`` and ``resume`` force it."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["auto", "fresh", "resume"] = "auto"
    conversation_uuid: Optional[str] = Field(None, max_length=64)


class SwarmWakeResponse(BaseModel):
    """``joined`` is true when a wake was already running and this call joined it instead of starting one."""

    state: str
    wake_id: int
    joined: bool


class SwarmCommit(BaseModel):
    """The memory commit of a sleep: ``status`` committed, nothing, skipped, pending_approval or refused_secret."""

    status: Optional[str] = None
    sha: Optional[str] = None
    skipped_reason: Optional[str] = None


class SwarmSleepResponse(BaseModel):
    """``POST /swarm/agents/{id}/sleep``: the state reached and the memory commit's outcome."""

    state: str
    commit: SwarmCommit = Field(default_factory=SwarmCommit)


class SwarmCheckpoint(BaseModel):
    """One commit of an agent's memory folder: ``kind`` is ``memory`` (a sleep commit), ``promotion``, ``flip_back`` or ``rewind``."""

    sha: str
    at: str
    subject: str
    kind: str


class SwarmCheckpointList(BaseModel):
    """``GET /swarm/agents/{id}/checkpoints``: newest first, at most 50; ``reason`` says why the list is empty."""

    commits: List[SwarmCheckpoint] = Field(default_factory=list)
    reason: Optional[str] = None


class SwarmRewindRequest(BaseModel):
    """``POST /swarm/agents/{id}/rewind``: the checkpoint's sha (full, or at least 7 hex characters)."""

    model_config = ConfigDict(extra="forbid")

    sha: str = Field(min_length=7, max_length=40, pattern="^[0-9a-f]+$")


class SwarmEarlierConversation(BaseModel):
    """One earlier conversation of an agent (a wake that recorded one); ``transcript_present`` is measured."""

    wake_id: int
    conversation_uuid: str
    started_at: str
    reason: Optional[str] = None
    authority: Optional[str] = None
    transcript_present: bool


class SwarmOwnerMessage(BaseModel):
    """``POST /swarm/agents/{id}/messages``: an owner order, 1 to 4000 characters."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class SwarmMessageResponse(BaseModel):
    """``message_ref`` is the huddle message (``huddle:msg:<id>``); ``outcome`` is delivered, held or waking."""

    message_ref: str
    outcome: Literal["delivered", "held", "waking"]


class SwarmCrumb(BaseModel):
    """One step of an entry's author path: ``agent_id`` is the live agent behind it, null when none is turned on or it was torn down."""

    kind: Literal["company", "project", "agent", "sysop", "owner"]
    name: str
    agent_id: Optional[int] = None


class SwarmQuestionAsker(BaseModel):
    """One agent that asked a question card's question, with its path as stored at ask time (first asker first)."""

    agent_id: Optional[int] = None
    name: str
    author_path: List[SwarmCrumb] = []


class SwarmQuestionCard(BaseModel):

    summary: str
    task: str
    details: str
    askers: List[SwarmQuestionAsker]
    asked_at: float


class SwarmOwnerEntry(BaseModel):
    """An owner message on the agent's thread. ``at`` is epoch seconds."""

    kind: Literal["owner"] = "owner"
    id: str
    at: float
    category: str = ""
    author_path: List[SwarmCrumb] = []
    text: str


class SwarmAgentEntry(BaseModel):
    """A message the agent wrote on its thread. ``at`` is epoch seconds. ``draft`` is set only on the live draft of a turn
    still running (``writing``) or one whose body stopped mid-answer (``stopped``); null on a posted message (docs/swarm.md 8.5)."""

    kind: Literal["agent"] = "agent"
    id: str
    at: float
    category: str = ""
    author_path: List[SwarmCrumb] = []
    text: str
    draft: Optional[Literal["writing", "stopped"]] = None


class SwarmCardEntry(BaseModel):

    kind: Literal["card"] = "card"
    id: str
    at: float
    category: str = ""
    card: Literal["done", "question", "review", "info"]
    item: Dict[str, Any]
    author_path: List[SwarmCrumb] = []
    question: Optional[SwarmQuestionCard] = None


class SwarmReceipt(BaseModel):
    """A crosstalk message's delivery state: ``status`` is queued, held, delivering, delivered, failed or expired."""

    status: str
    reason: Optional[str] = None
    delivered_at: Optional[float] = None


class SwarmTrafficEntry(BaseModel):
    """A crosstalk message to or from the agent (matched on its stable ``session_uuid``). ``direction`` is in or out."""

    kind: Literal["traffic"] = "traffic"
    id: str
    at: float
    category: str = ""
    direction: Literal["in", "out"]
    peer: str
    peer_session_uuid: Optional[str] = None
    author_path: List[SwarmCrumb] = []
    text: str
    summary: str = ""
    thread: str
    in_reply_to: Optional[str] = None
    receipt: SwarmReceipt


class SwarmEventEntry(BaseModel):
    """A Swarm event naming the agent; extra fields (``agent_id``, ``report_id``) ride along. ``card`` is a categorized card line."""

    model_config = ConfigDict(extra="allow")

    kind: Literal["event"] = "event"
    id: str
    at: float
    category: str = ""
    event: Literal["spawned", "reported", "accepted", "asked", "answered", "escalated", "learned", "promoted", "card"]
    ref: str
    text: str
    author_path: List[SwarmCrumb] = []


SwarmEntry = Union[SwarmOwnerEntry, SwarmAgentEntry, SwarmCardEntry, SwarmTrafficEntry, SwarmEventEntry]


class SwarmConversationPage(BaseModel):
    """``GET /swarm/agents/{id}/conversation``: entries oldest first; ``cursor`` is the newest entry's id (opaque)."""

    entries: List[SwarmEntry]
    cursor: Optional[str] = None


class SwarmSettings(BaseModel):
    """``GET`` and ``PUT /swarm/settings``: the caps and timers of the ``swarm`` config block (docs/swarm.md 4.1, 4.6, 7).

    A PUT carries only the fields it changes. ``max_children_per_parent``, ``max_live_bodies`` and ``spawn_load_per_core`` are
    optional (null = no cap, or the built-in load threshold; #1439): a PUT of null clears one. A tier with ``learning_batch_size`` queued learning items, or one older than
    ``learning_max_age_hours``, gets its own wake (docs/swarm.md 7). The last three fields are the Swarm page's (S6c): its
    default view, the drawer panel's default density, and the character set override (``theme`` follows the theme).
    ``upper_ranks_permissions`` is the launch posture of SysOp, company and project agents (``skip_all``: no permission
    prompts, the default; ``ask``: the pick AC prompting lockdown), applied at each one's next wake (docs/swarm.md 4.3).
    The Swarm look (#1426, docs/swarm.md 13.9): ``color_mode`` (``project`` or ``random``), ``shapes`` (a body shape per
    agent type: ``sysop``, ``company``, ``project``, ``agent``) and ``animations`` (a state's picked animation, or
    ``none``); a PUT of either map merges key by key. ``naming_family`` (off by default, #1444): on lets a project agent propose
    a naming family for its agents' persona names; off posts no naming-family review card and keeps plain names.
    """

    model_config = ConfigDict(extra="forbid")

    max_children_per_parent: Optional[int] = Field(None, ge=1, le=50)
    max_live_bodies: Optional[int] = Field(None, ge=1, le=200)
    spawn_load_per_core: Optional[float] = Field(None, ge=0.25, le=16.0)
    auto_sleep_idle_minutes: Optional[int] = Field(None, ge=1, le=1440)
    hop_timeout_minutes: Optional[int] = Field(None, ge=1, le=1440)
    closeout_window_minutes: Optional[int] = Field(None, ge=1, le=1440)
    closeout_default: Optional[Literal["teardown", "sleep"]] = None
    wake_hit_min_coverage: Optional[float] = Field(None, ge=0.0, le=1.0)
    learning_batch_size: Optional[int] = Field(None, ge=1, le=200)
    learning_max_age_hours: Optional[int] = Field(None, ge=1, le=720)
    flash_per_agent_per_hour: Optional[int] = Field(None, ge=1, le=20)
    flash_per_swarm_per_hour: Optional[int] = Field(None, ge=1, le=60)
    page_default_view: Optional[Literal["tree", "org", "squares"]] = None
    panel_default_density: Optional[Literal["condensed", "expanded", "detailed"]] = None
    character_pack: Optional[str] = Field(None, pattern=r"^[a-z0-9_-]{1,40}$")
    upper_ranks_permissions: Optional[Literal["skip_all", "ask"]] = None
    color_mode: Optional[Literal["project", "random"]] = None
    shapes: Optional[Dict[LookRank, LookShape]] = None
    animations: Optional[Dict[LookState, LookAnimation]] = None
    naming_family: Optional[bool] = None


class SwarmProjectSettings(BaseModel):
    """``GET`` and ``PUT /swarm/projects/{id}/settings``: the project's promotion threshold (docs/swarm.md 3.5)."""

    model_config = ConfigDict(extra="forbid")

    promotion_threshold: int = Field(5, ge=1, le=100)


class SwarmFact(BaseModel):
    """One fact of an agent's memory (``GET /swarm/agents/{id}/facts``): where it came from and whether it is live or held."""

    id: str
    agent_id: int
    title: str
    scope: Literal["craft", "project"]
    origin: Literal["owner", "agent", "handwritten"]
    owner_message_ref: Optional[str] = None
    taught_at: str
    taught_by_agent_id: Optional[int] = None
    state: Literal["live", "held", "killed"]


class SwarmFactScope(BaseModel):
    """``PATCH /swarm/facts/{id}``: the new scope."""

    model_config = ConfigDict(extra="forbid")

    scope: Literal["craft", "project"]


class SwarmKillResponse(BaseModel):
    """``DELETE /swarm/facts/{id}``: the ids of the questions the killed fact's answers rested on, now reopened (pick Y)."""

    reopened_question_ids: List[int]


class SwarmQuestionReceipt(BaseModel):
    """What a question's newest agent answer rested on, rendered by the server (``kind`` owner_fact, agent_fact or judgment)."""

    kind: Literal["owner_fact", "agent_fact", "judgment"]
    rendered: str
    fact_ids: List[str]


class SwarmQuestion(BaseModel):
    """One routed question (``GET /swarm/questions``). ``card_ref`` is the huddle item id of its nothing-hit card."""

    id: int
    text: str
    state: Literal["routing", "open", "answered", "reopened", "closed"]
    card_ref: Optional[str] = None
    answer_text: Optional[str] = None
    answered_by: Optional[str] = None
    created_at: str
    answered_at: Optional[str] = None
    askers: List[int]
    receipt: Optional[SwarmQuestionReceipt] = None


from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, NamedTuple, Optional

from src.core.agent_families import DEFAULT_FAMILY
from src.core.attention.registry_record import RegistryRecord
from src.core.attention.transcript_facts import TranscriptFacts

if TYPE_CHECKING:
    from src.core.approvals.extract import Dialog
    from src.core.attention.codex_reader import CodexEvidence
    from src.core.attention.screen_demand import ScreenDecision
    from src.core.attention.startup_screen import StartupScreen
    from src.core.background_work.measured import BackgroundMeasure
    from src.core.skill_fires.tally import SkillTally
    from src.core.subagents.parked_work import ParkedWork
    from src.core.subagents.tally import SubagentTally
    from src.core.timers.tally import TimerTally


STATE_DONE_IDLE: str = "done_idle"

STATE_NEEDS_USER: str = "needs_user"

STATE_BUSY: str = "busy"

STATE_UNKNOWN: str = "unknown"

ALL_STATES: frozenset = frozenset(
    {STATE_DONE_IDLE, STATE_NEEDS_USER, STATE_BUSY, STATE_UNKNOWN}
)


REASON_TURN_ENDED: str = "turn_ended"

REASON_QUESTION: str = "question"

REASON_PERMISSION: str = "permission"

REASON_PLAN_APPROVAL: str = "plan_approval"

REASON_INPUT: str = "input"

REASON_SUBAGENTS: str = "subagents"

REASON_QUEUED_REINVOKE: str = "queued_reinvoke"

REASON_STREAMING: str = "streaming"

REASON_TOOL: str = "tool"


REASON_REGISTRY_ABSENT: str = "registry_absent"

REASON_REGISTRY_STALE: str = "registry_stale"

REASON_REGISTRY_UNREADABLE: str = "registry_unreadable"

REASON_SHAPE_UNRECOGNIZED: str = "shape_unrecognized"

REASON_EVIDENCE_DISAGREES: str = "evidence_disagrees"

REASON_NO_EVIDENCE: str = "no_evidence"

REASON_PANE_DEAD: str = "pane_dead"

REASON_AMBIGUOUS_PANE: str = "ambiguous_pane"

REASON_RESTING_PROMPT: str = "resting_prompt"

REASON_STARTING: str = "starting"

ALL_REASONS: frozenset = frozenset(
    {
        REASON_TURN_ENDED,
        REASON_QUESTION,
        REASON_PERMISSION,
        REASON_PLAN_APPROVAL,
        REASON_INPUT,
        REASON_SUBAGENTS,
        REASON_QUEUED_REINVOKE,
        REASON_STREAMING,
        REASON_TOOL,
        REASON_REGISTRY_ABSENT,
        REASON_REGISTRY_STALE,
        REASON_REGISTRY_UNREADABLE,
        REASON_SHAPE_UNRECOGNIZED,
        REASON_EVIDENCE_DISAGREES,
        REASON_NO_EVIDENCE,
        REASON_PANE_DEAD,
        REASON_AMBIGUOUS_PANE,
        REASON_RESTING_PROMPT,
        REASON_STARTING,
    }
)


TIER_REGISTRY: str = "registry"

TIER_TRANSCRIPT: str = "transcript"

TIER_PANE: str = "pane"

TIER_TMUX: str = "tmux"

TIER_NONE: str = "none"

ALL_TIERS: frozenset = frozenset(
    {TIER_REGISTRY, TIER_TRANSCRIPT, TIER_PANE, TIER_TMUX, TIER_NONE}
)

FAMILY_CLAUDE: str = DEFAULT_FAMILY

FAMILY_CODEX: str = "codex"


@dataclass(frozen=True)
class PaneVerdict:

    permission_dialog: Optional[bool] = None

    question_dialog: Optional[bool] = None

    trust_dialog: Optional[bool] = None

    resting_prompt: Optional[bool] = None

    detail: str = ""

    @property
    def looked(self) -> bool:
        return (
            self.permission_dialog is not None
            or self.question_dialog is not None
            or self.trust_dialog is not None
        )

    @property
    def shows_dialog(self) -> bool:
        return self.permission_dialog is True or self.question_dialog is True

    @property
    def shows_no_dialog(self) -> bool:
        return self.permission_dialog is False and self.question_dialog is False


class EvidenceIdentity(NamedTuple):

    socket: Optional[str]
    tmux_name: Optional[str]
    epoch: Optional[int]
    pane_pid: Optional[int]
    conversation_uuid: Optional[str]

    @property
    def instance(self) -> tuple:
        return tuple(self[:4])

    @classmethod
    def coerce(cls, raw: Optional[tuple]) -> Optional["EvidenceIdentity"]:
        if raw is None or isinstance(raw, cls):
            return raw
        values = tuple(raw)[:5]
        return cls(*values, *([None] * (5 - len(values))))


def observed_conversation_uuid(evidence: Any) -> Optional[str]:
    identity = EvidenceIdentity.coerce(getattr(evidence, "identity", None))
    return identity.conversation_uuid if identity is not None else None


@dataclass(frozen=True)
class Evidence:

    tmux_liveness: str

    agent_family: Optional[str]

    registry: RegistryRecord

    transcript: TranscriptFacts

    pane: Optional[PaneVerdict]

    now: datetime

    resting_prompt_held: bool = False

    codex: Optional[CodexEvidence] = None

    identity: Optional[EvidenceIdentity] = None

    codex_bind_uuid: Optional[str] = None

    subagents: Optional[SubagentTally] = None

    timers: Optional[TimerTally] = None

    skills: Optional[SkillTally] = None

    parked_work: Optional[ParkedWork] = None

    dialog: Optional[Dialog] = None

    startup_screen: Optional[StartupScreen] = None

    screen_decision: Optional[ScreenDecision] = None

    prompt_suggestion: Optional[str] = None

    background_open: Optional[int] = None

    background_process: Optional[BackgroundMeasure] = None

    process_floor_at: Optional[datetime] = None

    def active_pane(self) -> Any:
        return self.codex.pane if self.codex is not None else self.pane

    def active_transcript(self) -> Any:
        return self.codex.transcript if self.codex is not None else self.transcript

    def append_at(self) -> Optional[datetime]:
        facts = self.active_transcript()
        return facts.last_append_at if self.codex is not None else facts.newest_append_at

    def dialog_clear(self) -> bool:
        pane = self.active_pane()
        if self.codex is not None:
            return pane is not None and pane.approval_dialog is False
        return pane is not None and pane.shows_no_dialog


@dataclass(frozen=True)
class AttentionVerdict:

    state: str

    reason: str

    tier: str

    pending_background_agents: Optional[int] = None

    settle_required: bool = False

    detail: str = ""

    pane_may_veto: bool = False

    activity_hint: Optional[str] = None

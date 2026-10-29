"""The shapes the attention resolver reads, and the shape it answers with.

DATA ONLY. Nothing in this module opens a file, shells out, reads a
clock or decides anything: it holds the four tiers of evidence in one
frozen bundle and names every string the resolver may put in a verdict.
The reading lives in ``registry_read``, ``transcript_facts`` and
``pane_markers``; the deciding lives in ``resolve``.

WHY THE STRINGS ARE CONSTANTS AND NOT LITERALS. A verdict is consumed by
the display mapping, the ledger, the raise gate and the tests, four
places that must agree on spelling. The project has already paid for a
string that was typed twice and drifted once (``docs/LESSONS.md``), so
no caller here types ``"needs_user"``; it imports :data:`STATE_NEEDS_USER`.

THE PANE'S TRI-STATE IS THE SHARPEST CASE. ``capture-pane`` against a
full-screen TUI returns trailing blanks and nothing else, so "the capture
came back empty" is not a measurement that no dialog is open. A pane we
did not look at, and a pane we looked at and could not read, both answer
``None``; only text we actually read and matched against answers False.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from src.core.agent_families import DEFAULT_FAMILY
from src.core.attention.registry_read import RegistryRecord
from src.core.attention.transcript_facts import TranscriptFacts


STATE_DONE_IDLE: str = "done_idle"

# permission prompt
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

# could not
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

    # could not
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


@dataclass(frozen=True)
class Evidence:

    tmux_liveness: str

    agent_family: Optional[str]

    registry: RegistryRecord

    transcript: TranscriptFacts

    pane: Optional[PaneVerdict]

    now: datetime

    resting_prompt_held: bool = False

    codex: Optional[Any] = None

    identity: Optional[tuple] = None

    codex_bind_uuid: Optional[str] = None

    subagents: Optional[Any] = None

    timers: Optional[Any] = None

    skills: Optional[Any] = None

    parked_work: Optional[Any] = None

    dialog: Optional[Any] = None

    startup_screen: Optional[Any] = None

    screen_decision: Optional[Any] = None

    background_open: Optional[int] = None

    background_process: Optional[Any] = None

    process_floor_at: Optional[datetime] = None


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

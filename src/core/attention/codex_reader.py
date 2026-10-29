"""The Codex family's attention resolution, in the resolver's own vocabulary.

THE FOUR TIERS AND WHAT EACH MAY SAY, restated so this file can check itself
against ``docs/session-status-model.md``:

- The RECORD tier (``thread_turns.status`` in ``~/.codex/thread_history_*
  .sqlite``) is the ONLY tier that may ORIGINATE rest. ``completed`` /
  ``interrupted`` / ``failed`` are rest; ``inProgress`` intersected with a LIVE
  writer-lock holder is busy; ``inProgress`` with no live holder, or a stale
  projection watermark, is ABSENT (never idle). See ``codex_stores.py``.
- The TRANSCRIPT tier (the rollout jsonl tail) may say a question is open or
  sub-agents are running; it may NEVER say rest.
- The PANE tier may CONFIRM an approval dialog, or (through a held resting
  prompt) VETO a busy record; it may NEVER originate rest.
- The TMUX tier alone may say dead.

THE ONE RULE THE WHOLE THING INHERITS: a guess never outranks a record, and an
absence is never a value. A record that could not be believed is absent, and an
absent record lands the session on ``unknown``, which raises nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.core.attention.usage_limit import UsageLimit
from src.core.attention.evidence import (
    REASON_NO_EVIDENCE,
    REASON_PANE_DEAD,
    REASON_PERMISSION,
    REASON_QUESTION,
    REASON_RESTING_PROMPT,
    REASON_SUBAGENTS,
    REASON_TOOL,
    REASON_TURN_ENDED,
    STATE_BUSY,
    STATE_DONE_IDLE,
    STATE_NEEDS_USER,
    STATE_UNKNOWN,
    TIER_NONE,
    TIER_PANE,
    TIER_REGISTRY,
    TIER_TMUX,
    TIER_TRANSCRIPT,
    AttentionVerdict,
    Evidence,
)
from src.core.session_status import LIVENESS_GONE

# could not

CODEX_RECORD_BUSY: str = "busy"

CODEX_RECORD_REST: str = "rest"

# could not
CODEX_RECORD_ABSENT: str = "absent"

CODEX_TURN_COMPLETED: str = "completed"
CODEX_TURN_INTERRUPTED: str = "interrupted"
CODEX_TURN_FAILED: str = "failed"

HINT_CODEX_INTERRUPTED: str = "codex_interrupted"
HINT_CODEX_TURN_FAILED: str = "codex_turn_failed"

_REST_HINTS = {
    CODEX_TURN_INTERRUPTED: HINT_CODEX_INTERRUPTED,
    CODEX_TURN_FAILED: HINT_CODEX_TURN_FAILED,
}


@dataclass(frozen=True)
class CodexRecordFacts:

    verdict: str = CODEX_RECORD_ABSENT
    rest_kind: str = ""


@dataclass(frozen=True)
class CodexTranscriptFacts:

    question_open: bool = False
    subagents_waiting: bool = False
    last_append_at: Optional[datetime] = None
    newest_user_prompt_at: Optional[datetime] = None
    usage_limit: Optional[UsageLimit] = None
    readable: bool = False
    detail: str = ""


@dataclass(frozen=True)
class CodexPaneFacts:

    approval_dialog: Optional[bool] = None
    trust_dialog: Optional[bool] = None
    resting_prompt: Optional[bool] = None
    working_marker: Optional[bool] = None
    detail: str = ""


@dataclass(frozen=True)
class CodexEvidence:

    record: CodexRecordFacts = CodexRecordFacts()
    transcript: CodexTranscriptFacts = CodexTranscriptFacts()
    pane: Optional[CodexPaneFacts] = None
    detail: str = ""


def _resting_held(pane: Optional[CodexPaneFacts], held: bool) -> bool:
    return bool(held and pane is not None and pane.resting_prompt is True)


def resolve_codex(
    codex: CodexEvidence,
    *,
    tmux_liveness: str,
    now: datetime,
    resting_prompt_held: bool = False,
) -> AttentionVerdict:
    record = codex.record
    transcript = codex.transcript
    pane = codex.pane
    held = _resting_held(pane, resting_prompt_held)

    if tmux_liveness == LIVENESS_GONE:
        return AttentionVerdict(
            state=STATE_UNKNOWN,
            reason=REASON_PANE_DEAD,
            tier=TIER_TMUX,
            detail="tmux measured this codex pane as gone",
        )

    if pane is not None and pane.approval_dialog is True:
        return AttentionVerdict(
            state=STATE_NEEDS_USER,
            reason=REASON_PERMISSION,
            tier=TIER_PANE,
            detail="codex is showing an approval dialog: %s"
            % (pane.detail or "would you like to run the following command"),
            settle_required=True,
        )

    if transcript.question_open:
        return AttentionVerdict(
            state=STATE_NEEDS_USER,
            reason=REASON_QUESTION,
            tier=TIER_TRANSCRIPT,
            detail=transcript.detail
            or "codex left a request_user_input open at the rollout tail",
            settle_required=True,
        )

    if record.verdict == CODEX_RECORD_REST:
        return AttentionVerdict(
            state=STATE_DONE_IDLE,
            reason=REASON_TURN_ENDED,
            tier=TIER_REGISTRY,
            detail="codex's own turn record reports the last turn %s"
            % (record.rest_kind or "ended"),
            activity_hint=_REST_HINTS.get(record.rest_kind),
        )

    if record.verdict == CODEX_RECORD_BUSY:
        if held:
            return _withdrawn(REASON_TOOL, TIER_REGISTRY)
        return AttentionVerdict(
            state=STATE_BUSY,
            reason=REASON_TOOL,
            tier=TIER_REGISTRY,
            detail="codex's own turn record reports a turn in progress and a "
            "live writer lock holds it",
            pane_may_veto=True,
        )

    # could not
    if transcript.subagents_waiting:
        if held:
            return _withdrawn(REASON_SUBAGENTS, TIER_TRANSCRIPT)
        return AttentionVerdict(
            state=STATE_BUSY,
            reason=REASON_SUBAGENTS,
            tier=TIER_TRANSCRIPT,
            detail=transcript.detail
            or "codex has an outstanding wait_agent with no turn close after it",
            pane_may_veto=True,
        )

    return AttentionVerdict(
        state=STATE_UNKNOWN,
        reason=REASON_NO_EVIDENCE,
        tier=TIER_NONE,
        detail=codex.detail
        or "codex's turn record, rollout tail and pane gave no readable "
        "status for this session",
    )


def _withdrawn(reason: str, tier: str) -> AttentionVerdict:
    return AttentionVerdict(
        state=STATE_UNKNOWN,
        reason=REASON_RESTING_PROMPT,
        tier=TIER_PANE,
        detail="the codex pane has been sitting on its resting prompt with no "
        "busy marker, so the %s verdict from the %s is withdrawn"
        % (reason, tier),
    )


def resolve_codex_evidence(evidence: Evidence) -> AttentionVerdict:
    codex = evidence.codex
    if not isinstance(codex, CodexEvidence):
        return AttentionVerdict(
            state=STATE_UNKNOWN,
            reason=REASON_NO_EVIDENCE,
            tier=TIER_NONE,
            detail="agent family codex has a reader but its stores were not "
            "gathered for this row, so its status is unknown",
        )
    return resolve_codex(
        codex,
        tmux_liveness=evidence.tmux_liveness,
        now=evidence.now,
        resting_prompt_held=evidence.resting_prompt_held,
    )

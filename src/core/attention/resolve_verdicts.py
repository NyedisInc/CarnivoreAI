
from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.core.attention.evidence import (
    REASON_PLAN_APPROVAL,
    REASON_QUESTION,
    REASON_QUEUED_REINVOKE,
    REASON_RESTING_PROMPT,
    REASON_SUBAGENTS,
    STATE_BUSY,
    STATE_UNKNOWN,
    TIER_PANE,
    AttentionVerdict,
    Evidence,
)
from src.core.attention.transcript_facts import FACTS_FOUND


def _age_seconds(now: datetime, at: Optional[datetime]) -> Optional[float]:
    if at is None:
        return None
    try:
        return (now - at).total_seconds()
    except TypeError:
        return None


def _turn_open_at_eof(evidence: Evidence) -> bool:
    """Did claude speak or call a tool after the last turn boundary?

    Description: PURE. The stand-in for "the window ends on an unanswered
      ``tool_use``", which TranscriptFacts does not expose for
      non-blocking tools (deviation 2 in the module docstring). An
      assistant record newer than the newest turn-end record means the
      current turn has produced output and has not ended, which is the
      shape a permission prompt leaves behind: claude emits the tool_use,
      then writes nothing at all until the human answers.

      A window with no turn-end record but with an assistant record
      counts as open, because the turn boundary is either behind the
      window or has not happened.
    Inputs: evidence (Evidence).
    Output: bool - False whenever the transcript could not be read.
    Example: _turn_open_at_eof(ev) -> True
    """
    facts = evidence.transcript
    if facts.newest_assistant_at is None:
        return False
    if facts.turn_end_at is None:
        return True
    return facts.newest_assistant_at > facts.turn_end_at


def _turn_at_rest(evidence: Evidence) -> bool:
    """Is the newest turn-end record the last word in the window?

    Description: PURE. The positive opposite of :func:`_turn_open_at_eof`,
      and not its negation: a transcript that could not be read is
      neither open nor at rest, and both answer False here.
    Inputs: evidence (Evidence).
    Output: bool.
    Example: _turn_at_rest(ev) -> True
    """
    facts = evidence.transcript
    if facts.verdict != FACTS_FOUND or facts.turn_end_at is None:
        return False
    if facts.newest_assistant_at is None:
        return True
    return facts.turn_end_at > facts.newest_assistant_at


def _pending_for_report(evidence: Evidence) -> Optional[int]:
    count = evidence.transcript.pending_background_agents
    if count is None:
        return None
    if evidence.registry.trusts_pending_count:
        return count
    if not evidence.registry.known:
        return count
    return None


def _verdict(
    state: str,
    reason: str,
    tier: str,
    detail: str,
    *,
    evidence: Evidence,
    settle: bool = False,
    pane_may_veto: bool = False,
) -> AttentionVerdict:
    return AttentionVerdict(
        state=state,
        reason=reason,
        tier=tier,
        pending_background_agents=_pending_for_report(evidence),
        settle_required=settle,
        detail=detail,
        pane_may_veto=pane_may_veto,
    )


def _busy_unless_resting(
    reason: str, tier: str, detail: str, *, evidence: Evidence
) -> AttentionVerdict:
    if evidence.resting_prompt_held and (
        reason in (REASON_SUBAGENTS, REASON_QUEUED_REINVOKE)
        and evidence.registry.confirms_background_work
    ):
        return _verdict(
            STATE_BUSY,
            reason,
            tier,
            "%s; claude's own session record says background work is "
            "still running" % detail,
            evidence=evidence,
            pane_may_veto=True,
        )
    if evidence.resting_prompt_held:
        return _verdict(
            STATE_UNKNOWN,
            REASON_RESTING_PROMPT,
            TIER_PANE,
            "the pane has been sitting on claude's resting input prompt "
            "with no busy marker on it, so this %s verdict from the %s is "
            "withdrawn rather than believed: %s"
            % (reason, tier, detail or "no detail was recorded"),
            evidence=evidence,
        )
    return _verdict(
        STATE_BUSY, reason, tier, detail, evidence=evidence, pane_may_veto=True
    )


def _blocked_tool_reason(tool: str) -> str:
    if tool == "ExitPlanMode":
        return REASON_PLAN_APPROVAL
    return REASON_QUESTION

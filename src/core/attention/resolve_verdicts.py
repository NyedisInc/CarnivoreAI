
from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.core.attention.evidence import (
    REASON_PLAN_APPROVAL,
    REASON_QUESTION,
    REASON_QUEUED_REINVOKE,
    REASON_RESTING_PROMPT,
    REASON_SUBAGENTS,
    REASON_TURN_ENDED,
    STATE_BUSY,
    STATE_DONE_IDLE,
    STATE_UNKNOWN,
    TIER_PANE,
    TIER_REGISTRY,
    AttentionVerdict,
    Evidence,
)
from src.core.attention.transcript_facts import FACTS_FOUND, TURN_END_INTERRUPT, TURN_END_NO_MODEL_TURN


def _age_seconds(now: datetime, at: Optional[datetime]) -> Optional[float]:
    if at is None:
        return None
    try:
        return (now - at).total_seconds()
    except TypeError:
        return None


def _turn_open_at_eof(evidence: Evidence) -> bool:
    facts = evidence.transcript
    if facts.newest_assistant_at is None:
        return False
    if facts.turn_end_at is None:
        return True
    return facts.newest_assistant_at > facts.turn_end_at


def _turn_at_rest(evidence: Evidence) -> bool:
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


def idle_turn_ended_verdict(
    evidence: Evidence, *, previous_process_only: bool, unprompted: bool, fresh: bool,
    status_age: Optional[float], quiet: Optional[float], still_appending: bool, shell_note: str,
) -> AttentionVerdict:
    facts = evidence.transcript

    corroborated = (
        ""
        if fresh
        else ", and that idle stamp is %.0fs old but the transcript "
        "corroborates it" % (status_age or 0.0)
    )
    if quiet is None:
        quiet_note = "there is no transcript to time"
    elif still_appending:
        quiet_note = (
            "the transcript appended %.1fs ago, which is the shell "
            "claude reports still running and not the turn" % quiet
        )
    else:
        quiet_note = "the transcript has been quiet for %.1fs" % quiet
    ended = {
        TURN_END_INTERRUPT: "the turn was stopped with an interrupt "
        "(Esc) with no agents pending",
        TURN_END_NO_MODEL_TURN: "no model turn has run yet, only "
        "local slash commands, so nothing is pending",
    }.get(facts.turn_end_kind, "the turn ended with no agents pending")
    if previous_process_only:
        ended = (
            "this claude process has written nothing to the "
            "transcript since it started, so it has run no turn"
        )
    elif unprompted:
        ended = (
            "no transcript exists yet and its status has not changed "
            "since it started, so it has never been prompted"
        )
    return _verdict(
        STATE_DONE_IDLE,
        REASON_TURN_ENDED,
        TIER_REGISTRY,
        "claude reports idle, %s and %s%s%s"
        % (ended, quiet_note, corroborated, shell_note),
        evidence=evidence,
    )

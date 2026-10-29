
from __future__ import annotations

from typing import Dict

from src.core.attention.background_claims import standing_background_claims
from src.core.attention.codex_reader import resolve_codex_evidence
from src.core.attention.evidence import (
    ALL_STATES,
    FAMILY_CLAUDE,
    FAMILY_CODEX,
    REASON_AMBIGUOUS_PANE,
    REASON_EVIDENCE_DISAGREES,
    REASON_INPUT,
    REASON_NO_EVIDENCE,
    REASON_PANE_DEAD,
    REASON_PERMISSION,
    REASON_QUESTION,
    REASON_QUEUED_REINVOKE,
    REASON_REGISTRY_ABSENT,
    REASON_REGISTRY_STALE,
    REASON_REGISTRY_UNREADABLE,
    REASON_SHAPE_UNRECOGNIZED,
    REASON_STARTING,
    REASON_STREAMING,
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
from src.core.attention.registry_read import (
    REG_ABSENT,
    REG_BUSY,
    REG_IDLE,
    REG_SHAPE_UNRECOGNIZED,
    REG_SHELL,
    REG_STALE,
    REG_WAITING,
    REGISTRY_STALE_AFTER_SECONDS,
)
from src.core.attention.question_part import with_question_hint
from src.core.attention.process_scope import never_prompted, transcript_predates_process
from src.core.attention.resolve_verdicts import (
    _age_seconds,
    _turn_open_at_eof,
    _turn_at_rest,
    _verdict,
    _busy_unless_resting,
    _blocked_tool_reason,
)
from src.core.attention.transcript_facts import (
    FACTS_FOUND,
    FACTS_SHAPE_UNRECOGNIZED,
    TURN_END_INTERRUPT,
    TURN_END_NO_MODEL_TURN,
)
from src.core.session_status import LIVENESS_GONE


SETTLE_SECONDS: float = 1.5

DONE_QUIET_SECONDS: int = 3

STREAMING_LOOKBACK_SECONDS: int = 120


WAITING_INPUT_NEEDED: str = "input needed"
WAITING_PERMISSION_PROMPT: str = "permission prompt"
WAITING_SANDBOX_REQUEST: str = "sandbox request"
WAITING_WORKER_REQUEST: str = "worker request"
WAITING_DIALOG_OPEN: str = "dialog open"

WAITING_REASONS: Dict[str, str] = {
    WAITING_INPUT_NEEDED: REASON_INPUT,
    WAITING_PERMISSION_PROMPT: REASON_PERMISSION,
    WAITING_SANDBOX_REQUEST: REASON_INPUT,
    WAITING_WORKER_REQUEST: REASON_INPUT,
    WAITING_DIALOG_OPEN: REASON_INPUT,
}

AMBIGUOUS_PANE_DETAIL_MARKER: str = "two or more live registry records"

_REGISTRY_REFUSAL_REASONS: Dict[str, str] = {
    REG_ABSENT: REASON_REGISTRY_ABSENT,
    REG_STALE: REASON_REGISTRY_STALE,
    REG_SHAPE_UNRECOGNIZED: REASON_SHAPE_UNRECOGNIZED,
}


def resolve_attention(evidence: Evidence) -> AttentionVerdict:
    return with_question_hint(_resolve_rungs(evidence), evidence)


def _resolve_rungs(evidence: Evidence) -> AttentionVerdict:
    registry = evidence.registry
    facts = evidence.transcript
    pane = evidence.pane

    if evidence.tmux_liveness == LIVENESS_GONE:
        return _verdict(
            STATE_UNKNOWN,
            REASON_PANE_DEAD,
            TIER_TMUX,
            "tmux measured this pane as gone",
            evidence=evidence,
        )

    if AMBIGUOUS_PANE_DETAIL_MARKER in registry.detail:
        return _verdict(
            STATE_UNKNOWN,
            REASON_AMBIGUOUS_PANE,
            TIER_REGISTRY,
            registry.detail,
            evidence=evidence,
        )

    # could not
    family = evidence.agent_family
    if family is not None and family != FAMILY_CLAUDE:
        if family == FAMILY_CODEX:
            return resolve_codex_evidence(evidence)
        if pane is not None and pane.shows_dialog:
            reason = (
                REASON_PERMISSION
                if pane.permission_dialog is True
                else REASON_QUESTION
            )
            return _verdict(
                STATE_NEEDS_USER,
                reason,
                TIER_PANE,
                "agent family %s has no registry reader yet; %s"
                % (family, pane.detail),
                evidence=evidence,
                settle=True,
            )
        return _verdict(
            STATE_UNKNOWN,
            REASON_NO_EVIDENCE,
            TIER_NONE,
            "agent family %s has no registry or transcript reader in this "
            "cut, and the pane showed no dialog" % family,
            evidence=evidence,
        )

    previous_process_only = transcript_predates_process(evidence)
    if facts.blocked_on_tool is not None and not previous_process_only:
        return _verdict(
            STATE_NEEDS_USER,
            _blocked_tool_reason(facts.blocked_on_tool),
            TIER_TRANSCRIPT,
            facts.detail,
            evidence=evidence,
            settle=True,
        )

    if pane is not None and pane.shows_dialog:
        reason = (
            REASON_PERMISSION if pane.permission_dialog is True else REASON_QUESTION
        )
        return _verdict(
            STATE_NEEDS_USER,
            reason,
            TIER_PANE,
            pane.detail,
            evidence=evidence,
            settle=True,
        )

    if facts.queued_reinvoke and not previous_process_only:
        return _busy_unless_resting(
            REASON_QUEUED_REINVOKE,
            TIER_TRANSCRIPT,
            facts.detail,
            evidence=evidence,
        )

    trusted_count = (
        facts.pending_background_agents
        if registry.trusts_pending_count
        else None
    )
    trusted_workflows = (
        facts.pending_workflows if registry.trusts_pending_count else None
    )
    open_shells = registry.known and standing_background_claims(evidence) > 0
    if not previous_process_only and (
        (trusted_count is not None and trusted_count > 0)
        or (trusted_workflows is not None and trusted_workflows > 0)
        or facts.open_async_agents > 0
        or open_shells
    ):
        return _busy_unless_resting(
            REASON_SUBAGENTS,
            TIER_TRANSCRIPT,
            facts.detail,
            evidence=evidence,
        )

    parked = None if previous_process_only else evidence.parked_work
    if parked is not None and parked.is_live:
        return _busy_unless_resting(
            REASON_SUBAGENTS, TIER_TRANSCRIPT, parked.detail, evidence=evidence
        )

    if registry.known and registry.status == REG_WAITING:
        # could not
        # could not be read
        if (pane is None or pane.permission_dialog is None) and _turn_open_at_eof(
            evidence
        ):
            return _verdict(
                STATE_NEEDS_USER,
                REASON_PERMISSION,
                TIER_TRANSCRIPT,
                "claude reports waiting and the turn is open at the end of "
                "the transcript; the pane could not be read, so this fails "
                "toward the user",
                evidence=evidence,
                settle=True,
            )

        reason = WAITING_REASONS.get(registry.waiting_for or "")
        vetoed = pane is not None and pane.shows_no_dialog
        if reason is not None and not vetoed:
            return _verdict(
                STATE_NEEDS_USER,
                reason,
                TIER_REGISTRY,
                "claude reports waiting for %s" % registry.waiting_for,
                evidence=evidence,
            )

        return _verdict(
            STATE_UNKNOWN,
            REASON_EVIDENCE_DISAGREES,
            TIER_REGISTRY,
            "claude reports waiting for %s and nothing corroborates it"
            % (registry.waiting_for or "an unnamed dialog"),
            evidence=evidence,
        )

    if registry.known and registry.status == REG_BUSY:
        # not allowed
        turn_end_newer = (
            facts.turn_end_at is not None
            and registry.status_updated_at is not None
            and facts.turn_end_at > registry.status_updated_at
        )
        if _turn_at_rest(evidence) and turn_end_newer:
            return _verdict(
                STATE_UNKNOWN,
                REASON_EVIDENCE_DISAGREES,
                TIER_REGISTRY,
                "claude reports busy but the transcript recorded the turn "
                "ending after that status was stamped",
                evidence=evidence,
            )

        streaming = not _turn_open_at_eof(evidence)
        return _busy_unless_resting(
            REASON_STREAMING if streaming else REASON_TOOL,
            TIER_REGISTRY,
            "claude reports busy and the transcript %s"
            % (
                "shows no output since the last turn end"
                if streaming
                else "shows an open turn at its end"
            ),
            evidence=evidence,
        )

    if registry.known and registry.status in (REG_IDLE, REG_SHELL):
        shell_note = (
            " (claude also reports a shell command it started still "
            "running)"
            if registry.status == REG_SHELL
            else ""
        )
        status_age = _age_seconds(evidence.now, registry.status_updated_at)
        fresh = status_age is not None and status_age < REGISTRY_STALE_AFTER_SECONDS
        quiet = _age_seconds(evidence.now, facts.newest_append_at)

        expected_shell_noise = registry.status == REG_SHELL
        settled = quiet is not None and (
            expected_shell_noise or quiet >= DONE_QUIET_SECONDS
        )

        unprompted = never_prompted(evidence)
        if registry.trusts_pending_count and (
            previous_process_only
            or unprompted
            or (
                facts.verdict == FACTS_FOUND
                and _turn_at_rest(evidence)
                and facts.pending_background_agents == 0
                and facts.open_async_agents == 0
                and not facts.queued_reinvoke
                and settled
                and not (parked is not None and parked.is_unmeasured)
            )
        ):
            corroborated = (
                ""
                if fresh
                else ", and that idle stamp is %.0fs old but the transcript "
                "corroborates it" % (status_age or 0.0)
            )
            if quiet is None:
                quiet_note = "there is no transcript to time"
            elif quiet < DONE_QUIET_SECONDS:
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

        if (
            quiet is not None
            and quiet < STREAMING_LOOKBACK_SECONDS
            and not _turn_at_rest(evidence)
            and facts.verdict != FACTS_SHAPE_UNRECOGNIZED
        ):
            return _verdict(
                STATE_BUSY,
                REASON_STREAMING,
                TIER_TRANSCRIPT,
                "claude reports idle but the transcript appended %.1fs ago "
                "with no turn end after the last assistant record%s"
                % (quiet, shell_note),
                evidence=evidence,
            )

        if parked is not None and parked.is_unmeasured:
            return _verdict(STATE_UNKNOWN, REASON_NO_EVIDENCE, TIER_TRANSCRIPT,
                            parked.detail, evidence=evidence)

        # could not
        if not fresh and facts.verdict != FACTS_SHAPE_UNRECOGNIZED:
            return _verdict(
                STATE_UNKNOWN,
                REASON_REGISTRY_STALE,
                TIER_REGISTRY,
                "claude reports idle but the record has not been updated "
                "inside %ds and nothing in the transcript corroborates a "
                "finished turn, so it may sustain a verdict and may not "
                "start one%s" % (REGISTRY_STALE_AFTER_SECONDS, shell_note),
                evidence=evidence,
            )
        return _verdict(
            STATE_UNKNOWN,
            REASON_SHAPE_UNRECOGNIZED
            if facts.verdict == FACTS_SHAPE_UNRECOGNIZED else REASON_NO_EVIDENCE,
            TIER_REGISTRY,
            "claude reports idle and the transcript does not confirm the "
            "turn ended with no agents pending: %s%s"
            % (facts.detail, shell_note),
            evidence=evidence,
        )

    if not registry.known:
        if previous_process_only:
            if registry.verdict == REG_ABSENT:
                return _verdict(
                    STATE_UNKNOWN,
                    REASON_STARTING,
                    TIER_REGISTRY,
                    "no claude has registered in this pane since %s, and every "
                    "transcript record predates it, so it describes a process "
                    "that is gone" % evidence.process_floor_at.isoformat()
                    if evidence.process_floor_at is not None
                    else "no claude has registered in this pane yet",
                    evidence=evidence,
                )
        elif (
            facts.pending_background_agents is not None
            and facts.pending_background_agents > 0
        ) or (facts.pending_workflows is not None and facts.pending_workflows > 0):
            return _verdict(
                STATE_BUSY,
                REASON_SUBAGENTS,
                TIER_TRANSCRIPT,
                "no usable registry record; " + facts.detail,
                evidence=evidence,
            )
        return _verdict(
            STATE_UNKNOWN,
            _REGISTRY_REFUSAL_REASONS.get(
                registry.verdict, REASON_REGISTRY_UNREADABLE
            ),
            TIER_REGISTRY,
            registry.detail or "no usable registry record for this session",
            evidence=evidence,
        )

    return _verdict(
        STATE_UNKNOWN,
        REASON_NO_EVIDENCE,
        TIER_NONE,
        "the registry reports a status this resolver does not recognise: %r"
        % registry.status,
        evidence=evidence,
    )


RESOLVED_STATES: frozenset = ALL_STATES

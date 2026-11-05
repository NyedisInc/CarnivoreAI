from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from src.core.attention.evidence import (
    REASON_NO_EVIDENCE,
    REASON_REGISTRY_STALE,
    REASON_SHAPE_UNRECOGNIZED,
    REASON_STREAMING,
    STATE_BUSY,
    STATE_UNKNOWN,
    TIER_REGISTRY,
    TIER_TRANSCRIPT,
    AttentionVerdict,
    Evidence,
)
from src.core.attention.process_scope import never_prompted
from src.core.attention.registry_record import REG_SHELL, REGISTRY_STALE_AFTER_SECONDS
from src.core.attention.resolve_verdicts import _age_seconds, _turn_at_rest, _verdict, idle_turn_ended_verdict
from src.core.attention.transcript_facts import FACTS_FOUND, FACTS_SHAPE_UNRECOGNIZED

if TYPE_CHECKING:
    from src.core.subagents.parked_work import ParkedWork

DONE_QUIET_SECONDS: int = 3

STREAMING_LOOKBACK_SECONDS: int = 120


@dataclass(frozen=True)
class RestReading:

    shell_note: str
    status_age: Optional[float]
    fresh: bool
    quiet: Optional[float]
    settled: bool
    parked: Optional["ParkedWork"]


def rest_reading(evidence: Evidence, previous_process_only: bool) -> RestReading:
    registry = evidence.registry
    facts = evidence.transcript
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
    parked = None if previous_process_only else evidence.parked_work
    return RestReading(shell_note=shell_note, status_age=status_age, fresh=fresh, quiet=quiet, settled=settled, parked=parked)


def rung_8_turn_ended(evidence: Evidence, previous_process_only: bool, reading: RestReading) -> Optional[AttentionVerdict]:
    registry = evidence.registry
    facts = evidence.transcript
    parked = reading.parked
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
            and reading.settled
            and not (parked is not None and parked.is_unmeasured)
        )
    ):
        return idle_turn_ended_verdict(
            evidence, previous_process_only=previous_process_only, unprompted=unprompted, fresh=reading.fresh,
            status_age=reading.status_age, quiet=reading.quiet, shell_note=reading.shell_note,
            still_appending=reading.quiet is not None and reading.quiet < DONE_QUIET_SECONDS,
        )
    return None


def rung_8b_streaming(evidence: Evidence, reading: RestReading) -> Optional[AttentionVerdict]:
    facts, quiet, shell_note = evidence.transcript, reading.quiet, reading.shell_note
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
    return None


def rung_8c_unmeasured_agent(evidence: Evidence, reading: RestReading) -> Optional[AttentionVerdict]:
    parked = reading.parked
    if parked is not None and parked.is_unmeasured:
        return _verdict(STATE_UNKNOWN, REASON_NO_EVIDENCE, TIER_TRANSCRIPT,
                        parked.detail, evidence=evidence)
    return None


def rest_refused(evidence: Evidence, reading: RestReading) -> AttentionVerdict:
    facts, fresh, shell_note = evidence.transcript, reading.fresh, reading.shell_note
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

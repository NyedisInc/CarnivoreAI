
from __future__ import annotations

from datetime import datetime, timezone

from src.core.attention.codex_reader import (
    CODEX_RECORD_ABSENT,
    CODEX_RECORD_BUSY,
    CODEX_RECORD_REST,
    CODEX_TURN_COMPLETED,
    CODEX_TURN_FAILED,
    CODEX_TURN_INTERRUPTED,
    HINT_CODEX_INTERRUPTED,
    HINT_CODEX_TURN_FAILED,
    CodexEvidence,
    CodexPaneFacts,
    CodexRecordFacts,
    CodexTranscriptFacts,
    resolve_codex,
)
from src.core.attention.display import to_display
from src.core.attention.evidence import (
    ALL_REASONS,
    ALL_STATES,
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
)
from src.core.session_status import (
    LIVENESS_GONE,
    LIVENESS_LIVE,
    STATUS_DEAD,
    STATUS_QUESTION,
    STATUS_WORKING,
    STATUS_WORKING_SUBAGENT,
)

NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)


def _record(verdict: str, rest_kind: str = "") -> CodexRecordFacts:
    return CodexRecordFacts(verdict=verdict, rest_kind=rest_kind)


def _transcript(
    *, question_open: bool = False, subagents_waiting: bool = False
) -> CodexTranscriptFacts:
    return CodexTranscriptFacts(
        question_open=question_open,
        subagents_waiting=subagents_waiting,
        readable=True,
    )


def _evidence(
    *,
    record: CodexRecordFacts = None,
    transcript: CodexTranscriptFacts = None,
    pane: CodexPaneFacts = None,
) -> CodexEvidence:
    return CodexEvidence(
        record=record if record is not None else _record(CODEX_RECORD_ABSENT),
        transcript=transcript if transcript is not None else _transcript(),
        pane=pane,
    )


def _resolve(ce: CodexEvidence, *, live=LIVENESS_LIVE, held=False):
    return resolve_codex(
        ce, tmux_liveness=live, now=NOW, resting_prompt_held=held
    )


def _assert(verdict, state, reason, tier):
    assert verdict.state == state, verdict
    assert verdict.reason == reason, verdict
    assert verdict.tier == tier, verdict
    assert verdict.state in ALL_STATES
    assert verdict.reason in ALL_REASONS




def test_completed_turn_is_done_idle_from_the_record():
    ce = _evidence(record=_record(CODEX_RECORD_REST, CODEX_TURN_COMPLETED))
    v = _resolve(ce)
    _assert(v, STATE_DONE_IDLE, REASON_TURN_ENDED, TIER_REGISTRY)
    assert v.activity_hint is None
    assert to_display(v, unread=False, tmux_status="running") == "idle"


def test_inprogress_with_a_live_lock_is_busy():
    ce = _evidence(record=_record(CODEX_RECORD_BUSY))
    v = _resolve(ce)
    _assert(v, STATE_BUSY, REASON_TOOL, TIER_REGISTRY)
    assert to_display(v, unread=False, tmux_status="running") == STATUS_WORKING


def test_inprogress_without_a_live_lock_is_unknown_never_idle():
    ce = _evidence(record=_record(CODEX_RECORD_ABSENT))
    v = _resolve(ce)
    _assert(v, STATE_UNKNOWN, REASON_NO_EVIDENCE, TIER_NONE)
    assert to_display(v, unread=False, tmux_status="running") != "idle"


def test_interrupted_turn_is_rest_with_a_hint():
    ce = _evidence(record=_record(CODEX_RECORD_REST, CODEX_TURN_INTERRUPTED))
    v = _resolve(ce)
    _assert(v, STATE_DONE_IDLE, REASON_TURN_ENDED, TIER_REGISTRY)
    assert v.activity_hint == HINT_CODEX_INTERRUPTED


def test_failed_turn_is_rest_with_a_hint():
    ce = _evidence(record=_record(CODEX_RECORD_REST, CODEX_TURN_FAILED))
    v = _resolve(ce)
    _assert(v, STATE_DONE_IDLE, REASON_TURN_ENDED, TIER_REGISTRY)
    assert v.activity_hint == HINT_CODEX_TURN_FAILED




def test_record_busy_is_withdrawn_by_a_held_resting_pane():
    ce = _evidence(
        record=_record(CODEX_RECORD_BUSY),
        pane=CodexPaneFacts(resting_prompt=True),
    )
    v = _resolve(ce, held=True)
    _assert(v, STATE_UNKNOWN, REASON_RESTING_PROMPT, TIER_PANE)
    assert v.state != STATE_DONE_IDLE


def test_record_busy_stays_busy_when_a_working_marker_is_on_the_pane():
    ce = _evidence(
        record=_record(CODEX_RECORD_BUSY),
        pane=CodexPaneFacts(resting_prompt=False, working_marker=True),
    )
    v = _resolve(ce, held=False)
    _assert(v, STATE_BUSY, REASON_TOOL, TIER_REGISTRY)




def test_open_request_user_input_is_a_question():
    ce = _evidence(transcript=_transcript(question_open=True))
    v = _resolve(ce)
    _assert(v, STATE_NEEDS_USER, REASON_QUESTION, TIER_TRANSCRIPT)
    assert v.settle_required is True
    assert to_display(v, unread=False, tmux_status="running") == STATUS_QUESTION


def test_outstanding_wait_agent_is_working_subagent():
    ce = _evidence(transcript=_transcript(subagents_waiting=True))
    v = _resolve(ce)
    _assert(v, STATE_BUSY, REASON_SUBAGENTS, TIER_TRANSCRIPT)
    assert (
        to_display(v, unread=False, tmux_status="running")
        == STATUS_WORKING_SUBAGENT
    )


def test_a_completed_record_outranks_a_stale_wait_agent():
    ce = _evidence(
        record=_record(CODEX_RECORD_REST, CODEX_TURN_COMPLETED),
        transcript=_transcript(subagents_waiting=True),
    )
    v = _resolve(ce)
    _assert(v, STATE_DONE_IDLE, REASON_TURN_ENDED, TIER_REGISTRY)


def test_subagents_waiting_is_also_withdrawn_by_a_held_resting_pane():
    ce = _evidence(
        transcript=_transcript(subagents_waiting=True),
        pane=CodexPaneFacts(resting_prompt=True),
    )
    v = _resolve(ce, held=True)
    _assert(v, STATE_UNKNOWN, REASON_RESTING_PROMPT, TIER_PANE)




def test_pane_approval_dialog_is_needs_user():
    ce = _evidence(pane=CodexPaneFacts(approval_dialog=True))
    v = _resolve(ce)
    _assert(v, STATE_NEEDS_USER, REASON_PERMISSION, TIER_PANE)
    assert v.settle_required is True


def test_needs_user_outranks_a_busy_record():
    ce = _evidence(
        record=_record(CODEX_RECORD_BUSY),
        transcript=_transcript(subagents_waiting=True),
        pane=CodexPaneFacts(approval_dialog=True),
    )
    v = _resolve(ce)
    _assert(v, STATE_NEEDS_USER, REASON_PERMISSION, TIER_PANE)
    assert v.settle_required is True




def test_pane_dead_is_dead():
    ce = _evidence(record=_record(CODEX_RECORD_BUSY))
    v = _resolve(ce, live=LIVENESS_GONE)
    _assert(v, STATE_UNKNOWN, REASON_PANE_DEAD, TIER_TMUX)
    assert to_display(v, unread=False, tmux_status="running") == STATUS_DEAD




def test_nothing_readable_is_honest_unknown():
    v = _resolve(_evidence())
    _assert(v, STATE_UNKNOWN, REASON_NO_EVIDENCE, TIER_NONE)
    assert "codex" in v.detail.lower()
    assert to_display(v, unread=False, tmux_status="running") != "idle"




def _outer(codex_bundle, *, family="codex"):
    from src.core.attention.evidence import Evidence
    from src.core.attention.registry_read import registry_for_session
    from src.core.attention.transcript_facts import FACTS_UNREADABLE, TranscriptFacts

    return Evidence(
        tmux_liveness=LIVENESS_LIVE,
        agent_family=family,
        registry=registry_for_session(tmux_name=None),
        transcript=TranscriptFacts(verdict=FACTS_UNREADABLE),
        pane=None,
        now=NOW,
        codex=codex_bundle,
    )


def test_rule_e_dispatches_a_codex_row_to_the_codex_reader():
    from src.core.attention.resolve import resolve_attention

    bundle = _evidence(record=_record(CODEX_RECORD_REST, CODEX_TURN_COMPLETED))
    v = resolve_attention(_outer(bundle))
    _assert(v, STATE_DONE_IDLE, REASON_TURN_ENDED, TIER_REGISTRY)


def test_rule_e_codex_without_a_bundle_is_honest_unknown():
    from src.core.attention.resolve import resolve_attention

    v = resolve_attention(_outer(None))
    _assert(v, STATE_UNKNOWN, REASON_NO_EVIDENCE, TIER_NONE)
    assert "codex" in v.detail.lower()


def test_rule_e_a_reader_less_family_stays_honest_unknown():
    from src.core.attention.resolve import resolve_attention

    v = resolve_attention(_outer(None, family="hermes"))
    _assert(v, STATE_UNKNOWN, REASON_NO_EVIDENCE, TIER_NONE)
    assert "hermes" in v.detail.lower()

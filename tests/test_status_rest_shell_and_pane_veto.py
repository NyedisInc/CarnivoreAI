
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.core.attention.display import (
    ACTIVITY_HINT_SHELL,
    activity_hint_for,
    status_source_for,
    to_display,
)
from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    REASON_INPUT,
    REASON_REGISTRY_STALE,
    REASON_PERMISSION,
    REASON_QUESTION,
    REASON_QUEUED_REINVOKE,
    REASON_RESTING_PROMPT,
    REASON_STREAMING,
    REASON_SUBAGENTS,
    REASON_TURN_ENDED,
    STATE_BUSY,
    STATE_DONE_IDLE,
    STATE_NEEDS_USER,
    STATE_UNKNOWN,
    TIER_PANE,
    TIER_REGISTRY,
    TIER_TRANSCRIPT,
    Evidence,
    PaneVerdict,
)
from src.core.attention.pane_markers import (
    RESTING_TAIL_LINES,
    classify_pane_tail,
)
from src.core.attention.registry_record import REG_BUSY, REG_IDLE, REG_SHELL, parse_registry_record
from src.core.attention.registry_index import registry_for_session
from src.core.attention.resolve import DONE_QUIET_SECONDS, resolve_attention
from src.core.attention.transcript_walk import BOOKKEEPING_RECORD_TYPES
from src.core.attention.transcript_facts import (
    FACTS_FOUND,
    TranscriptFacts,
    classify_transcript_records,
)
from src.core.session_status import (
    LIVENESS_GONE,
    LIVENESS_LIVE,
    STATUS_IDLE,
    STATUS_QUESTION,
    STATUS_UNKNOWN,
    STATUS_WORKING_SUBAGENT,
)
from src.core.session_status_source import STATUS_SOURCE_PANE


NOW = datetime(2026, 9, 18, 6, 0, 0, tzinfo=timezone.utc)

ARGENT_REGISTRY_PAYLOAD = {
    "sessionId": "90c5c356-e7d1-4151-b385-78eab7f60f4d",
    "cwd": "/Users/alex/Projects/Acme/ALEX-Docs",
    "pid": 91992,
    "startedAt": 1788294281973,
    "version": "2.1.266",
    "kind": "interactive",
    "entrypoint": "cli",
    "tmux": "cloude_Argent:@3.%3",
    "status": "shell",
    "updatedAt": 1788857113338,
    "statusUpdatedAt": 1788857113338,
}

TMUX_NAME = "cloude_Argent"


def _millis(at: datetime) -> int:
    return int(at.timestamp() * 1000)


def _registry(status: str, *, status_age: float = 10.0):
    payload = dict(ARGENT_REGISTRY_PAYLOAD)
    payload["status"] = status
    payload["statusUpdatedAt"] = _millis(NOW - timedelta(seconds=status_age))
    return parse_registry_record(payload, path_pid=None)


REGISTRY_ABSENT = registry_for_session(tmux_name=TMUX_NAME, index={})


def _at_rest(*, pending: int = 0, quiet: float = 10.0, **fields) -> TranscriptFacts:
    end = NOW - timedelta(seconds=quiet)
    base = dict(
        pending_background_agents=pending,
        pending_field_present=True,
        turn_end_at=end,
        newest_assistant_at=end - timedelta(seconds=1),
        newest_append_at=end,
        detail="the turn ended with %s background agents pending" % pending,
    )
    base.update(fields)
    return TranscriptFacts(verdict=FACTS_FOUND, **base)


def _evidence(
    *,
    registry=None,
    transcript: TranscriptFacts = None,
    pane: PaneVerdict = None,
    resting_prompt_held: bool = False,
    tmux_liveness: str = LIVENESS_LIVE,
    now: datetime = NOW,
) -> Evidence:
    return Evidence(
        tmux_liveness=tmux_liveness,
        agent_family=FAMILY_CLAUDE,
        registry=registry if registry is not None else REGISTRY_ABSENT,
        transcript=(
            transcript
            if transcript is not None
            else TranscriptFacts(verdict=FACTS_FOUND)
        ),
        pane=pane,
        resting_prompt_held=resting_prompt_held,
        now=now,
    )


def _axes(verdict) -> tuple:
    return (verdict.state, verdict.reason, verdict.tier)




def test_a_real_shell_record_at_rest_reaches_done_idle_not_busy():
    verdict = resolve_attention(
        _evidence(registry=_registry(REG_SHELL), transcript=_at_rest())
    )
    assert _axes(verdict) == (
        STATE_DONE_IDLE,
        REASON_TURN_ENDED,
        TIER_REGISTRY,
    ), verdict.detail


def test_shell_and_idle_answer_identically_on_the_same_transcript():
    transcript = _at_rest()
    shell = resolve_attention(
        _evidence(registry=_registry(REG_SHELL), transcript=transcript)
    )
    idle = resolve_attention(
        _evidence(registry=_registry(REG_IDLE), transcript=transcript)
    )
    assert _axes(shell) == _axes(idle)


def test_shell_with_a_moving_transcript_is_still_read_as_streaming():
    moving = TranscriptFacts(
        verdict=FACTS_FOUND,
        newest_assistant_at=NOW - timedelta(seconds=2),
        newest_append_at=NOW - timedelta(seconds=2),
        turn_end_at=NOW - timedelta(seconds=40),
        detail="claude spoke after the last turn end",
    )
    verdict = resolve_attention(
        _evidence(registry=_registry(REG_SHELL), transcript=moving)
    )
    assert _axes(verdict) == (STATE_BUSY, REASON_STREAMING, TIER_TRANSCRIPT)


def test_a_stale_shell_nothing_corroborates_refuses_rather_than_resting():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_SHELL, status_age=10 * 24 * 3600),
            transcript=TranscriptFacts(verdict=FACTS_FOUND, detail="nothing"),
        )
    )
    assert verdict.state == STATE_UNKNOWN, verdict.detail


def test_the_shell_hint_is_the_status_word_and_nothing_else_is():
    assert activity_hint_for(_registry(REG_SHELL)) == ACTIVITY_HINT_SHELL
    assert activity_hint_for(_registry(REG_IDLE)) is None
    assert activity_hint_for(_registry(REG_BUSY)) is None
    assert activity_hint_for(REGISTRY_ABSENT) is None


def test_a_vetoed_or_dead_session_still_reports_its_shell_hint_from_the_record():
    assert activity_hint_for(_registry(REG_SHELL, status_age=9 * 24 * 3600)) == (
        ACTIVITY_HINT_SHELL
    )




def _shell_with_a_chatty_transcript(*, status_age: float, quiet: float):
    end = NOW - timedelta(seconds=quiet + 600)
    return _evidence(
        registry=_registry(REG_SHELL, status_age=status_age),
        transcript=_at_rest(
            quiet=quiet,
            turn_end_at=end,
            newest_assistant_at=end - timedelta(seconds=1),
        ),
    )


def test_a_shell_record_at_rest_rests_even_while_its_shell_keeps_writing():
    verdict = resolve_attention(
        _shell_with_a_chatty_transcript(status_age=3600, quiet=0.5)
    )

    assert _axes(verdict) == (
        STATE_DONE_IDLE,
        REASON_TURN_ENDED,
        TIER_REGISTRY,
    ), verdict.detail
    assert "quiet for" not in verdict.detail
    assert "shell" in verdict.detail


def test_a_plain_idle_record_with_a_moving_file_is_unchanged():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE, status_age=3600),
            transcript=_at_rest(
                quiet=0.5,
                turn_end_at=NOW - timedelta(seconds=600),
                newest_assistant_at=NOW - timedelta(seconds=601),
            ),
        )
    )

    assert verdict.state == STATE_UNKNOWN, verdict.detail
    assert verdict.reason == REASON_REGISTRY_STALE


def test_a_quiet_shell_record_answers_exactly_as_it_did_before():
    verdict = resolve_attention(
        _shell_with_a_chatty_transcript(status_age=3600, quiet=10.0)
    )

    assert _axes(verdict) == (STATE_DONE_IDLE, REASON_TURN_ENDED, TIER_REGISTRY)
    assert "quiet for 10.0s" in verdict.detail
    assert 10.0 > DONE_QUIET_SECONDS


def test_the_exception_cannot_carry_a_record_with_no_turn_end():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_SHELL, status_age=3600),
            transcript=TranscriptFacts(
                verdict=FACTS_FOUND,
                newest_append_at=NOW - timedelta(seconds=600),
                detail="no turn-end record in the window",
            ),
        )
    )

    assert verdict.state == STATE_UNKNOWN, verdict.detail
    assert verdict.reason == REASON_REGISTRY_STALE


def test_an_unmeasured_append_time_is_still_not_a_quiet_transcript():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_SHELL, status_age=3600),
            transcript=_at_rest(newest_append_at=None),
        )
    )

    assert verdict.state == STATE_UNKNOWN, verdict.detail


def test_a_busy_record_never_reaches_the_shell_exception():
    moving = TranscriptFacts(
        verdict=FACTS_FOUND,
        newest_assistant_at=NOW - timedelta(seconds=2),
        newest_append_at=NOW - timedelta(seconds=0.5),
        turn_end_at=NOW - timedelta(seconds=40),
        detail="claude spoke after the last turn end",
    )
    verdict = resolve_attention(
        _evidence(registry=_registry(REG_BUSY), transcript=moving)
    )

    assert verdict.state == STATE_BUSY, verdict.detail



QUESTION_TOOL_USE_ID = "toolu_01ZoWBWebGgGYU5OYGiwW2nC"


def _ts(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (at.microsecond // 1000)


def _turn_end_record(at: datetime, *, pending: int = 1) -> dict:
    return {
        "type": "system",
        "subtype": "turn_duration",
        "timestamp": _ts(at),
        "version": "2.1.266",
        "pendingBackgroundAgentCount": pending,
    }


def _ask_user_question_record(at: datetime) -> dict:
    return {
        "type": "assistant",
        "timestamp": _ts(at),
        "version": "2.1.266",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": QUESTION_TOOL_USE_ID,
                    "name": "AskUserQuestion",
                    "input": {"questions": [{"question": "which one"}]},
                }
            ],
        },
    }


def _attachment_record(at: datetime) -> dict:
    return {
        "parentUuid": "00000000-0000-4000-8000-000000000001",
        "isSidechain": False,
        "attachment": {
            "type": "queued_command",
            "prompt": (
                "<task-notification>\n<task-id>aaaa1111</task-id>\n"
                "<tool-use-id>toolu_0004231114031332455674</tool-use-id>\n"
                "<status>completed</status>\n"
                "<summary>Agent finished</summary>\n</task-notification>"
            ),
            "source_uuid": "00000000-0000-4000-8000-000000000002",
            "commandMode": "prompt",
            "origin": {"kind": "agent"},
            "timestamp": _ts(at),
        },
        "type": "attachment",
        "uuid": "00000000-0000-4000-8000-000000000003",
        "timestamp": _ts(at),
        "rendered": [{"content": "<system-reminder>a task finished</system-reminder>"}],
        "renderedInHumanTurn": True,
        "userType": "external",
        "entrypoint": "cli",
        "version": "2.1.266",
    }


def _task_notification_record(at: datetime) -> dict:
    return {
        "type": "user",
        "timestamp": _ts(at),
        "version": "2.1.266",
        "message": {
            "role": "user",
            "content": (
                "<task-notification>\n<task-id>aaaa1111</task-id>\n"
                "<tool-use-id>toolu_0004231114031332455674</tool-use-id>\n"
                "<status>completed</status>\n</task-notification>"
            ),
        },
    }


def test_attachment_is_a_bookkeeping_type_the_walk_skips():
    assert "attachment" in BOOKKEEPING_RECORD_TYPES


def test_an_open_question_above_an_attachment_record_is_still_named():
    asked = NOW - timedelta(minutes=4)
    records = [
        _turn_end_record(asked - timedelta(seconds=20), pending=1),
        _ask_user_question_record(asked),
        _attachment_record(asked + timedelta(seconds=64)),
        _attachment_record(asked + timedelta(seconds=82)),
    ]
    facts = classify_transcript_records(records, now=NOW)

    assert facts.blocked_on_tool == "AskUserQuestion", facts.detail
    verdict = resolve_attention(
        _evidence(registry=_registry(REG_BUSY), transcript=facts)
    )
    assert _axes(verdict) == (STATE_NEEDS_USER, REASON_QUESTION, TIER_TRANSCRIPT)
    assert to_display(verdict, unread=False, tmux_status=STATUS_UNKNOWN) == (
        STATUS_QUESTION
    )


def test_an_answered_question_under_an_attachment_stays_silent():
    asked = NOW - timedelta(minutes=4)
    answer = {
        "type": "user",
        "timestamp": _ts(asked + timedelta(seconds=30)),
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": QUESTION_TOOL_USE_ID,
                    "content": "the second one",
                }
            ],
        },
    }
    records = [
        _turn_end_record(asked - timedelta(seconds=20), pending=0),
        _ask_user_question_record(asked),
        answer,
        _attachment_record(asked + timedelta(seconds=64)),
    ]
    facts = classify_transcript_records(records, now=NOW)
    assert facts.blocked_on_tool is None, facts.detail


def test_a_user_record_still_stops_the_walk_dead():
    asked = NOW - timedelta(minutes=4)
    records = [
        _turn_end_record(asked - timedelta(seconds=20), pending=1),
        _ask_user_question_record(asked),
        _task_notification_record(asked + timedelta(seconds=90)),
    ]
    facts = classify_transcript_records(records, now=NOW)
    assert facts.blocked_on_tool is None, facts.detail


def test_no_attachment_record_in_the_corpus_can_close_a_dialog():
    record = _attachment_record(NOW)
    assert "message" not in record
    assert not isinstance(record.get("message"), dict)



ARGENT_RESTING_CAPTURE = [
    "  ⎿  Referenced file TODO.md",
    "  ⎿  Skills restored (sme)",
    "⏺ Remote Control disconnected - run /remote-control to start a session",
    "",
    "─" * 60 + " ALEX-Docs ─",
    "❯ ",
    "─" * 62,
    "  ALEX-Docs | git:(main) | Opus 5 (1M context) | 0% | think:high",
    "  ⏵⏵ bypass permissions on · 1 monitor · ← 1 agent",
]

ARGENT_RESTING_NO_TASKS = ARGENT_RESTING_CAPTURE[:-1] + [
    "  ⏵⏵ bypass permissions on · ← 1 agent",
]

BACKGROUND_AGENT_CAPTURE = [
    "⏺ diag agent pulling the raw tier inputs off every live session",
    "",
    "✻ Waiting for 1 background agent to finish",
    "",
    "─" * 60 + " cloudecode-notifications ─",
    "❯ fix it so a resting prompt clears the stale working state",
    "─" * 62,
    "  cloudecode | git:(master) | Fable 5.1 | 20% | think:xhigh",
    "  ⏵⏵ bypass permissions on · ← 1 agent",
    "",
    "  ⏺ main",
    "  ◯ general-purpose  Writing diag.py evidence capture script      4m 6s",
]

SPINNER_CAPTURE = [
    "⏺ Reading the resolver",
    "",
    "✻ Harmonizing… (49s · ↓ 1.2k tokens · esc to interrupt)",
    "─" * 60,
    "❯ ",
    "─" * 62,
    "  cloudecode | git:(master) | Fable 5.1",
]

INTERRUPT_ONLY_CAPTURE = [
    "⏺ Writing the test file",
    "⏵ running · esc to interrupt",
    "─" * 60,
    "❯ ",
    "─" * 62,
]

MCP_TASK_CAPTURE = [
    "⏺ Asked the server for the index",
    "✽ Fetching the catalog · 2 MCP tasks still running",
    "─" * 60,
    "❯ ",
    "─" * 62,
]

QUESTION_MENU_CAPTURE = [
    "❯ 1. Design study on nostromo (Recommended)",
    "     Svelte app in the design worktree, served with the mockup's data.",
    "  2. Real front end in the main repo",
    "  3. Type something.",
    "─" * 62,
    "  4. Chat about this",
    "",
    "Enter to select · Tab/Arrow keys to navigate · Esc to cancel",
]

CODEX_CAPTURE = [
    "⚠ MCP startup incomplete (failed: google-ads, meta-ads)",
    "  1 background terminal running · /ps to view · /stop to close",
    "› Ask Codex to do anything",
    "  esc again to edit previous message",
]


def test_a_resting_prompt_is_measured_true_on_the_argent_capture():
    verdict = classify_pane_tail(ARGENT_RESTING_NO_TASKS)
    assert verdict.resting_prompt is True, verdict.detail
    assert classify_pane_tail(ARGENT_RESTING_CAPTURE).resting_prompt is False


def test_a_background_agent_line_above_the_prompt_is_not_resting():
    verdict = classify_pane_tail(BACKGROUND_AGENT_CAPTURE)
    assert verdict.resting_prompt is False, verdict.detail


@pytest.mark.parametrize(
    "capture, why",
    [
        (SPINNER_CAPTURE, "a progress line with an elapsed time"),
        (INTERRUPT_ONLY_CAPTURE, "the interrupt footer alone"),
        (MCP_TASK_CAPTURE, "an MCP task still running"),
    ],
)
def test_a_busy_marker_anywhere_in_the_live_region_refuses_resting(capture, why):
    """Every busy marker refuses the claim on its own. NEGATIVE CONTROLS.

    Each capture ends on a prompt line, so without its marker each one
    would read as resting. That is what makes these the controls for the
    marker list rather than three spellings of one case.
    """
    verdict = classify_pane_tail(capture)
    assert verdict.resting_prompt is False, "%s: %s" % (why, verdict.detail)


def test_a_dialog_on_screen_is_never_resting_even_with_a_prompt_glyph():
    verdict = classify_pane_tail(QUESTION_MENU_CAPTURE)
    assert verdict.question_dialog is True, verdict.detail
    assert verdict.resting_prompt is False, verdict.detail


def test_a_capture_with_no_claude_prompt_says_nothing_about_resting():
    verdict = classify_pane_tail(CODEX_CAPTURE)
    assert verdict.resting_prompt is False, verdict.detail


def test_a_blank_capture_answers_none_for_resting_too():
    verdict = classify_pane_tail([])
    assert verdict.resting_prompt is None
    assert classify_pane_tail(None).resting_prompt is None


def test_a_stale_busy_marker_far_above_the_live_region_is_out_of_scope():
    lines = ["✻ Waiting for 1 background agent to finish"]
    lines += ["  line %d of prose" % n for n in range(RESTING_TAIL_LINES + 4)]
    lines += ["─" * 60, "❯ ", "─" * 62]
    verdict = classify_pane_tail(lines)
    assert verdict.resting_prompt is True, verdict.detail



PANE_RESTING = classify_pane_tail(ARGENT_RESTING_NO_TASKS)
PANE_WORKING = classify_pane_tail(BACKGROUND_AGENT_CAPTURE)


def _latched_subagents() -> TranscriptFacts:
    return _at_rest(pending=1, quiet=40 * 60)


def test_a_latched_subagent_count_under_a_held_resting_prompt_becomes_unknown():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_BUSY),
            transcript=_latched_subagents(),
            pane=PANE_RESTING,
            resting_prompt_held=True,
        )
    )
    assert _axes(verdict) == (STATE_UNKNOWN, REASON_RESTING_PROMPT, TIER_PANE)
    assert to_display(verdict, unread=False, tmux_status=STATUS_UNKNOWN) == (
        STATUS_UNKNOWN
    )
    assert status_source_for(verdict) == STATUS_SOURCE_PANE


def test_a_resting_prompt_that_has_not_been_held_long_enough_changes_nothing():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_BUSY),
            transcript=_latched_subagents(),
            pane=PANE_RESTING,
            resting_prompt_held=False,
        )
    )
    assert _axes(verdict) == (STATE_BUSY, REASON_SUBAGENTS, TIER_TRANSCRIPT)


def test_the_queued_reinvoke_rung_is_vetoed_too():
    facts = _at_rest(pending=0, quiet=40 * 60, queued_reinvoke=True)
    held = resolve_attention(
        _evidence(
            registry=_registry(REG_BUSY),
            transcript=facts,
            pane=PANE_RESTING,
            resting_prompt_held=True,
        )
    )
    assert _axes(held) == (STATE_UNKNOWN, REASON_RESTING_PROMPT, TIER_PANE)
    loose = resolve_attention(
        _evidence(registry=_registry(REG_BUSY), transcript=facts)
    )
    assert _axes(loose) == (STATE_BUSY, REASON_QUEUED_REINVOKE, TIER_TRANSCRIPT)


def test_the_registry_busy_rung_is_vetoed_too():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_BUSY, status_age=40 * 60),
            transcript=_at_rest(pending=0, quiet=40 * 60),
            pane=PANE_RESTING,
            resting_prompt_held=True,
        )
    )
    assert verdict.state == STATE_UNKNOWN, verdict.detail
    assert verdict.reason == REASON_RESTING_PROMPT


def test_a_working_pane_under_a_busy_verdict_leaves_it_alone():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_BUSY),
            transcript=_latched_subagents(),
            pane=PANE_WORKING,
            resting_prompt_held=False,
        )
    )
    assert _axes(verdict) == (STATE_BUSY, REASON_SUBAGENTS, TIER_TRANSCRIPT)
    assert to_display(verdict, unread=False, tmux_status=STATUS_UNKNOWN) == (
        STATUS_WORKING_SUBAGENT
    )


def test_an_open_dialog_outranks_the_veto_and_still_paints_a_question():
    facts = _at_rest(pending=1, quiet=40 * 60, blocked_on_tool="AskUserQuestion")
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_BUSY),
            transcript=facts,
            pane=PANE_RESTING,
            resting_prompt_held=True,
        )
    )
    assert _axes(verdict) == (STATE_NEEDS_USER, REASON_QUESTION, TIER_TRANSCRIPT)


def test_a_needs_user_registry_waiting_is_never_vetoed():
    waiting_payload = dict(ARGENT_REGISTRY_PAYLOAD)
    waiting_payload["status"] = "waiting"
    waiting_payload["waitingFor"] = "input needed"
    waiting_payload["statusUpdatedAt"] = _millis(NOW - timedelta(seconds=10))
    record = parse_registry_record(waiting_payload, path_pid=None)
    verdict = resolve_attention(
        _evidence(
            registry=record,
            transcript=TranscriptFacts(verdict=FACTS_FOUND, detail="nothing"),
            pane=None,
            resting_prompt_held=True,
        )
    )
    assert verdict.state == STATE_NEEDS_USER, verdict.detail
    assert verdict.reason in (REASON_INPUT, REASON_PERMISSION)


def test_a_dead_pane_is_never_vetoed_into_unknown_by_the_pane():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_BUSY),
            transcript=_latched_subagents(),
            pane=PANE_RESTING,
            resting_prompt_held=True,
            tmux_liveness=LIVENESS_GONE,
        )
    )
    assert verdict.reason != REASON_RESTING_PROMPT
    assert verdict.state == STATE_UNKNOWN


def test_a_genuinely_idle_registry_still_reaches_the_rest_block():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE),
            transcript=_at_rest(),
            pane=PANE_RESTING,
            resting_prompt_held=True,
        )
    )
    assert _axes(verdict) == (
        STATE_DONE_IDLE,
        REASON_TURN_ENDED,
        TIER_REGISTRY,
    ), verdict.detail
    assert to_display(verdict, unread=False, tmux_status=STATUS_UNKNOWN) == STATUS_IDLE


def test_the_veto_needs_the_held_flag_and_not_merely_a_resting_pane():
    for held in (False, True):
        verdict = resolve_attention(
            _evidence(
                registry=_registry(REG_BUSY),
                transcript=_latched_subagents(),
                pane=PANE_RESTING,
                resting_prompt_held=held,
            )
        )
        assert (verdict.reason == REASON_RESTING_PROMPT) is held, verdict.detail




def test_the_listing_reports_the_status_its_source_and_the_hint():
    from src.core import listing_attention

    status, source, hint = listing_attention.resolve_row_status(
        registry=_registry(REG_SHELL),
        transcript=_at_rest(),
        tmux_liveness=LIVENESS_LIVE,
        agent_family=FAMILY_CLAUDE,
        pane=None,
        unread=False,
        tmux_status=STATUS_UNKNOWN,
        now=NOW,
    )
    assert (status, source, hint) == (STATUS_IDLE, "registry", ACTIVITY_HINT_SHELL)


def test_a_row_with_no_hint_reports_none_and_not_a_blank():
    from src.core import listing_attention

    status, source, hint = listing_attention.resolve_row_status(
        registry=_registry(REG_IDLE),
        transcript=_at_rest(),
        tmux_liveness=LIVENESS_LIVE,
        agent_family=FAMILY_CLAUDE,
        pane=None,
        unread=False,
        tmux_status=STATUS_UNKNOWN,
        now=NOW,
    )
    assert (status, source) == (STATUS_IDLE, "registry")
    assert hint is None


def test_session_info_declares_the_field_so_it_survives_the_response_filter():
    from src.models.sessions import SessionInfo

    fields = SessionInfo.model_fields
    assert "activity_hint" in fields, "the wrapper must declare the field"
    assert fields["activity_hint"].default is None
    from src.models.sessions import Session

    assert "activity_hint" not in Session.model_fields

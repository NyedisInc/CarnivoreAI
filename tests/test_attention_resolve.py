
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from src.core.attention.display import to_display
from src.core.attention.evidence import (
    ALL_REASONS,
    ALL_STATES,
    FAMILY_CLAUDE,
    REASON_AMBIGUOUS_PANE,
    REASON_EVIDENCE_DISAGREES,
    REASON_INPUT,
    REASON_NO_EVIDENCE,
    REASON_PANE_DEAD,
    REASON_PERMISSION,
    REASON_PLAN_APPROVAL,
    REASON_QUESTION,
    REASON_QUEUED_REINVOKE,
    REASON_REGISTRY_ABSENT,
    REASON_REGISTRY_STALE,
    REASON_REGISTRY_UNREADABLE,
    REASON_RESTING_PROMPT,
    REASON_STARTING,
    REASON_SHAPE_UNRECOGNIZED,
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
    PaneVerdict,
)
from src.core.attention.pane_markers import classify_pane_tail
from src.core.attention.registry_record import (
    REG_BUSY,
    REG_IDLE,
    REG_OK,
    REG_SHELL,
    REG_UNREADABLE,
    REG_WAITING,
    REGISTRY_STALE_AFTER_SECONDS,
    parse_registry_record,
)
from src.core.attention.registry_index import pid_is_running, registry_for_session
from src.core.attention.resolve import (
    DONE_QUIET_SECONDS,
    STREAMING_LOOKBACK_SECONDS,
    WAITING_DIALOG_OPEN,
    WAITING_INPUT_NEEDED,
    WAITING_PERMISSION_PROMPT,
    WAITING_SANDBOX_REQUEST,
    WAITING_WORKER_REQUEST,
    resolve_attention,
)
from src.core.attention.transcript_facts import (
    FACTS_FOUND,
    FACTS_NO_RECORD,
    FACTS_UNREADABLE,
    TranscriptFacts,
)
from src.core.session_status import (
    LIVENESS_GONE,
    LIVENESS_LIVE,
    LIVENESS_UNKNOWN,
    STATUS_DEAD,
    STATUS_FINISHED_UNREAD,
    STATUS_IDLE,
    STATUS_NOTICE,
    STATUS_QUESTION,
    STATUS_RUNNING,
    STATUS_UNKNOWN,
    STATUS_WORKING,
    STATUS_WORKING_SUBAGENT,
)


NOW = datetime(2026, 9, 13, 18, 0, 0, tzinfo=timezone.utc)

REGISTRY_PAYLOAD = {
    "sessionId": "2adb9dfb-605d-f5b6-9a53-25e7380a3a8f",
    "cwd": "/Users/alex/Projects/My Projects/Cloude Code Repos/Dev/cloudecode",
    "pid": 51292,
    "startedAt": 1789095742551,
    "version": "2.1.266",
    "kind": "interactive",
    "entrypoint": "cli",
    "tmux": "cloude_cloudecode-2:@205.%205",
    "status": "idle",
    "updatedAt": 1789327656518,
    "statusUpdatedAt": 1789327655830,
}

TMUX_NAME = "cloude_cloudecode-2"

LATER_THAN_STARTED_EPOCH = 1789095742 + 60


def _millis(at: datetime) -> int:
    return int(at.timestamp() * 1000)


def _registry(
    status: str,
    *,
    waiting_for: str = None,
    version: object = "2.1.266",
    status_age: float = 10.0,
):
    payload = dict(REGISTRY_PAYLOAD)
    payload["status"] = status
    payload["version"] = version
    payload["statusUpdatedAt"] = _millis(NOW - timedelta(seconds=status_age))
    if waiting_for is not None:
        payload["waitingFor"] = waiting_for
    return parse_registry_record(payload, path_pid=None)


REGISTRY_ABSENT = registry_for_session(tmux_name=TMUX_NAME, index={})

REGISTRY_UNREADABLE = parse_registry_record({"status": "idle"}, path_pid=None)

REGISTRY_SHAPE_UNRECOGNIZED = parse_registry_record({}, path_pid=None)

REGISTRY_STALE = registry_for_session(
    tmux_name=TMUX_NAME,
    index={TMUX_NAME: _registry(REG_IDLE)},
    session_started_epoch=LATER_THAN_STARTED_EPOCH,
)


def _facts(verdict: str = FACTS_FOUND, **fields) -> TranscriptFacts:
    return TranscriptFacts(verdict=verdict, **fields)


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


def _turn_open(*, quiet: float = 2.0, **fields) -> TranscriptFacts:
    spoke = NOW - timedelta(seconds=quiet)
    base = dict(
        turn_end_at=spoke - timedelta(seconds=30),
        newest_assistant_at=spoke,
        newest_append_at=spoke,
        detail="claude spoke after the last turn end and stopped",
    )
    base.update(fields)
    return TranscriptFacts(verdict=FACTS_FOUND, **base)


def _evidence(
    *,
    registry=None,
    transcript: TranscriptFacts = None,
    pane: PaneVerdict = None,
    tmux_liveness: str = LIVENESS_LIVE,
    family: str = FAMILY_CLAUDE,
    now: datetime = NOW,
) -> Evidence:
    return Evidence(
        tmux_liveness=tmux_liveness,
        agent_family=family,
        registry=registry if registry is not None else REGISTRY_ABSENT,
        transcript=transcript if transcript is not None else _facts(FACTS_NO_RECORD),
        pane=pane,
        now=now,
    )


PANE_PERMISSION = PaneVerdict(
    permission_dialog=True,
    question_dialog=False,
    trust_dialog=False,
    detail="matched permission",
)

PANE_QUESTION = PaneVerdict(
    permission_dialog=False,
    question_dialog=True,
    trust_dialog=False,
    detail="matched question",
)

PANE_CLEAR = PaneVerdict(
    permission_dialog=False,
    question_dialog=False,
    trust_dialog=False,
    detail="matched no dialog family",
)

PANE_BLANK = classify_pane_tail([])


def _assert_verdict(
    verdict: AttentionVerdict, state: str, reason: str, tier: str
) -> None:
    assert (verdict.state, verdict.reason, verdict.tier) == (
        state,
        reason,
        tier,
    ), verdict.detail




def test_rung_0_a_pane_tmux_measured_gone_outranks_every_other_tier():
    verdict = resolve_attention(
        _evidence(
            tmux_liveness=LIVENESS_GONE,
            registry=_registry(REG_IDLE),
            transcript=_at_rest(pending=0),
        )
    )

    _assert_verdict(verdict, STATE_UNKNOWN, REASON_PANE_DEAD, TIER_TMUX)
    assert verdict.settle_required is False


def test_rung_1_two_live_records_on_one_pane_refuse_instead_of_picking(tmp_path):
    first = os.getpid()
    second = os.getppid()
    if pid_is_running(second) is not True or second == first:
        pytest.skip("no second live pid available to collide with")

    for pid in (first, second):
        body = dict(REGISTRY_PAYLOAD, pid=pid, status=REG_WAITING)
        (tmp_path / ("%d.json" % pid)).write_text(json.dumps(body), encoding="utf-8")

    record = registry_for_session(tmux_name=TMUX_NAME, directory=str(tmp_path))
    assert record.verdict == REG_UNREADABLE
    assert record.ambiguous_pane is True

    verdict = resolve_attention(
        _evidence(
            registry=record,
            transcript=_at_rest(queued_reinvoke=True),
        )
    )

    _assert_verdict(verdict, STATE_UNKNOWN, REASON_AMBIGUOUS_PANE, TIER_REGISTRY)
    assert str(first) in verdict.detail and str(second) in verdict.detail


def test_rung_3_a_queued_reinvoke_outranks_a_finished_turn():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE),
            transcript=_at_rest(pending=0, queued_reinvoke=True),
        )
    )

    _assert_verdict(verdict, STATE_BUSY, REASON_QUEUED_REINVOKE, TIER_TRANSCRIPT)
    assert verdict.settle_required is False


def test_rung_4_background_agents_outrank_everything_the_registry_says():
    counted = resolve_attention(
        _evidence(registry=_registry(REG_IDLE), transcript=_at_rest(pending=2))
    )
    _assert_verdict(counted, STATE_BUSY, REASON_SUBAGENTS, TIER_TRANSCRIPT)
    assert counted.pending_background_agents == 2

    ledgered = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE),
            transcript=_at_rest(pending=0, open_async_agents=1),
        )
    )
    _assert_verdict(ledgered, STATE_BUSY, REASON_SUBAGENTS, TIER_TRANSCRIPT)


def test_rung_2_the_transcript_names_which_question_is_open():
    question = resolve_attention(
        _evidence(
            registry=_registry(REG_WAITING, waiting_for=WAITING_INPUT_NEEDED),
            transcript=_turn_open(blocked_on_tool="AskUserQuestion"),
        )
    )
    _assert_verdict(question, STATE_NEEDS_USER, REASON_QUESTION, TIER_TRANSCRIPT)
    assert question.settle_required is True

    plan = resolve_attention(
        _evidence(
            registry=_registry(REG_WAITING, waiting_for=WAITING_PERMISSION_PROMPT),
            transcript=_turn_open(blocked_on_tool="ExitPlanMode"),
        )
    )
    _assert_verdict(plan, STATE_NEEDS_USER, REASON_PLAN_APPROVAL, TIER_TRANSCRIPT)


def test_rung_2_an_open_question_outranks_background_agents_still_running():
    asked_while_working = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE),
            transcript=_turn_open(
                blocked_on_tool="AskUserQuestion",
                pending_background_agents=1,
                pending_field_present=True,
            ),
        )
    )
    _assert_verdict(
        asked_while_working, STATE_NEEDS_USER, REASON_QUESTION, TIER_TRANSCRIPT
    )
    assert asked_while_working.settle_required is True

    ledgered = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE),
            transcript=_turn_open(
                blocked_on_tool="ExitPlanMode", open_async_agents=2
            ),
        )
    )
    _assert_verdict(
        ledgered, STATE_NEEDS_USER, REASON_PLAN_APPROVAL, TIER_TRANSCRIPT
    )

    also_queued = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE),
            transcript=_turn_open(
                blocked_on_tool="AskUserQuestion",
                queued_reinvoke=True,
                pending_background_agents=3,
                pending_field_present=True,
            ),
        )
    )
    _assert_verdict(
        also_queued, STATE_NEEDS_USER, REASON_QUESTION, TIER_TRANSCRIPT
    )

    for status in (REG_BUSY, REG_WAITING, REG_SHELL):
        verdict = resolve_attention(
            _evidence(
                registry=_registry(status),
                transcript=_turn_open(
                    blocked_on_tool="AskUserQuestion",
                    pending_background_agents=1,
                    pending_field_present=True,
                ),
            )
        )
        _assert_verdict(verdict, STATE_NEEDS_USER, REASON_QUESTION, TIER_TRANSCRIPT)


def test_rung_5_a_dialog_on_screen_outranks_what_the_registry_is_waiting_for():
    permission = resolve_attention(
        _evidence(
            registry=_registry(REG_WAITING, waiting_for=WAITING_INPUT_NEEDED),
            transcript=_at_rest(),
            pane=PANE_PERMISSION,
        )
    )
    _assert_verdict(permission, STATE_NEEDS_USER, REASON_PERMISSION, TIER_PANE)
    assert permission.settle_required is True

    question = resolve_attention(
        _evidence(
            registry=_registry(REG_WAITING, waiting_for=WAITING_INPUT_NEEDED),
            transcript=_at_rest(),
            pane=PANE_QUESTION,
        )
    )
    _assert_verdict(question, STATE_NEEDS_USER, REASON_QUESTION, TIER_PANE)


def test_rung_5b_an_unreadable_pane_over_an_open_turn_fails_toward_the_human():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_WAITING, waiting_for=WAITING_INPUT_NEEDED),
            transcript=_turn_open(),
            pane=None,
        )
    )

    _assert_verdict(verdict, STATE_NEEDS_USER, REASON_PERMISSION, TIER_TRANSCRIPT)
    assert verdict.settle_required is True


@pytest.mark.parametrize(
    "waiting_for, reason",
    [
        (WAITING_INPUT_NEEDED, REASON_INPUT),
        (WAITING_PERMISSION_PROMPT, REASON_PERMISSION),
        (WAITING_SANDBOX_REQUEST, REASON_INPUT),
        (WAITING_WORKER_REQUEST, REASON_INPUT),
        (WAITING_DIALOG_OPEN, REASON_INPUT),
    ],
)
def test_rung_5c_claude_names_what_it_is_waiting_for_and_is_believed(
    waiting_for, reason
):
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_WAITING, waiting_for=waiting_for),
            transcript=_at_rest(),
            pane=None,
        )
    )

    _assert_verdict(verdict, STATE_NEEDS_USER, reason, TIER_REGISTRY)
    assert verdict.settle_required is False


def test_rung_5d_a_waiting_nothing_corroborates_refuses_rather_than_picking():
    vetoed = resolve_attention(
        _evidence(
            registry=_registry(REG_WAITING, waiting_for=WAITING_INPUT_NEEDED),
            transcript=_at_rest(),
            pane=PANE_CLEAR,
        )
    )
    _assert_verdict(vetoed, STATE_UNKNOWN, REASON_EVIDENCE_DISAGREES, TIER_REGISTRY)

    unnamed = resolve_attention(
        _evidence(
            registry=_registry(REG_WAITING, waiting_for="something new in 2.2"),
            transcript=_at_rest(),
            pane=None,
        )
    )
    _assert_verdict(unnamed, STATE_UNKNOWN, REASON_EVIDENCE_DISAGREES, TIER_REGISTRY)


def test_rung_6_a_registry_busy_is_refined_by_the_shape_at_the_end_of_the_window():
    streaming = resolve_attention(
        _evidence(
            registry=_registry(REG_BUSY, status_age=1.0),
            transcript=_at_rest(quiet=10.0),
        )
    )
    _assert_verdict(streaming, STATE_BUSY, REASON_STREAMING, TIER_REGISTRY)
    assert streaming.settle_required is False

    running_a_tool = resolve_attention(
        _evidence(
            registry=_registry(REG_BUSY, status_age=1.0),
            transcript=_turn_open(quiet=2.0),
        )
    )
    _assert_verdict(running_a_tool, STATE_BUSY, REASON_TOOL, TIER_REGISTRY)


def test_rung_6a_a_busy_older_than_the_turn_end_it_contradicts_refuses():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_BUSY, status_age=60.0),
            transcript=_at_rest(quiet=10.0),
        )
    )

    _assert_verdict(verdict, STATE_UNKNOWN, REASON_EVIDENCE_DISAGREES, TIER_REGISTRY)


def test_rung_7_is_gone_and_a_shell_record_takes_the_rest_path():
    verdict = resolve_attention(
        _evidence(registry=_registry(REG_SHELL), transcript=_at_rest())
    )

    _assert_verdict(verdict, STATE_DONE_IDLE, REASON_TURN_ENDED, TIER_REGISTRY)
    assert verdict.settle_required is False


def test_rung_8_the_only_path_to_done_idle_needs_every_gate_at_once():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE, status_age=10.0),
            transcript=_at_rest(pending=0, quiet=DONE_QUIET_SECONDS + 1),
        )
    )

    _assert_verdict(verdict, STATE_DONE_IDLE, REASON_TURN_ENDED, TIER_REGISTRY)
    assert verdict.settle_required is False
    assert verdict.pending_background_agents == 0

    never_written = _evidence(
        registry=_registry(REG_IDLE),
        transcript=_at_rest(pending=None, pending_field_present=False),
    )
    assert resolve_attention(never_written).state != STATE_DONE_IDLE
    assert resolve_attention(never_written).pending_background_agents is None

    still_quieting = _evidence(
        registry=_registry(REG_IDLE),
        transcript=_at_rest(pending=0, quiet=DONE_QUIET_SECONDS - 1),
    )
    assert resolve_attention(still_quieting).state != STATE_DONE_IDLE


def test_rung_8_a_turn_whose_count_was_omitted_still_reaches_done_idle():
    omitted = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE, status_age=10.0),
            transcript=_at_rest(
                pending=0,
                pending_field_present=False,
                quiet=DONE_QUIET_SECONDS + 1,
            ),
        )
    )

    _assert_verdict(omitted, STATE_DONE_IDLE, REASON_TURN_ENDED, TIER_REGISTRY)
    assert omitted.pending_background_agents == 0

    no_record = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE, status_age=10.0),
            transcript=_facts(
                FACTS_NO_RECORD,
                newest_append_at=NOW - timedelta(seconds=DONE_QUIET_SECONDS + 1),
            ),
        )
    )
    assert no_record.state != STATE_DONE_IDLE
    assert no_record.pending_background_agents is None


def test_rung_8b_an_idle_over_a_transcript_still_moving_is_still_generating():
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE, status_age=5.0),
            transcript=_turn_open(quiet=5.0),
        )
    )

    _assert_verdict(verdict, STATE_BUSY, REASON_STREAMING, TIER_TRANSCRIPT)

    long_ago = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE, status_age=5.0),
            transcript=_turn_open(quiet=STREAMING_LOOKBACK_SECONDS + 1),
        )
    )
    assert long_ago.state == STATE_UNKNOWN


@pytest.mark.parametrize(
    "record, reason",
    [
        (REGISTRY_ABSENT, REASON_REGISTRY_ABSENT),
        (REGISTRY_STALE, REASON_REGISTRY_STALE),
        (REGISTRY_UNREADABLE, REASON_REGISTRY_UNREADABLE),
        (REGISTRY_SHAPE_UNRECOGNIZED, REASON_SHAPE_UNRECOGNIZED),
    ],
)
def test_rung_9_without_a_registry_the_transcript_may_say_busy_but_never_done(
    record, reason
):
    refused = resolve_attention(
        _evidence(registry=record, transcript=_at_rest(pending=0))
    )
    _assert_verdict(refused, STATE_UNKNOWN, reason, TIER_REGISTRY)

    blocked = resolve_attention(
        _evidence(registry=record, transcript=_turn_open(blocked_on_tool="AskUserQuestion"))
    )
    _assert_verdict(blocked, STATE_NEEDS_USER, REASON_QUESTION, TIER_TRANSCRIPT)
    assert blocked.settle_required is True

    agents = resolve_attention(
        _evidence(registry=record, transcript=_at_rest(pending=3))
    )
    _assert_verdict(agents, STATE_BUSY, REASON_SUBAGENTS, TIER_TRANSCRIPT)


def test_rung_10_a_status_string_this_resolver_does_not_know_refuses():
    verdict = resolve_attention(
        _evidence(registry=_registry("compacting"), transcript=_at_rest())
    )

    _assert_verdict(verdict, STATE_UNKNOWN, REASON_NO_EVIDENCE, TIER_NONE)
    assert "compacting" in verdict.detail




PANE_TABLE = [
    ("no capture attempted", None),
    ("capture held no text", PANE_BLANK),
    ("read and clear", PANE_CLEAR),
    ("permission prompt", PANE_PERMISSION),
    ("question menu", PANE_QUESTION),
    ("trust dialog only", PaneVerdict(trust_dialog=True, detail="matched trust")),
    (
        "permission and question at once",
        PaneVerdict(permission_dialog=True, question_dialog=True, detail="both"),
    ),
]


def test_rule_a_no_pane_input_over_any_registry_refusal_can_produce_done_idle():
    registries = [
        ("absent", REGISTRY_ABSENT),
        ("stale", REGISTRY_STALE),
        ("unreadable", REGISTRY_UNREADABLE),
        ("shape unrecognized", REGISTRY_SHAPE_UNRECOGNIZED),
        ("waiting", _registry(REG_WAITING, waiting_for=WAITING_INPUT_NEEDED)),
        ("busy", _registry(REG_BUSY, status_age=1.0)),
        ("unrecognised status", _registry("compacting")),
    ]

    for pane_name, pane in PANE_TABLE:
        for registry_name, registry in registries:
            verdict = resolve_attention(
                _evidence(
                    registry=registry,
                    transcript=_at_rest(pending=0),
                    pane=pane,
                )
            )
            where = "%s pane over a %s registry" % (pane_name, registry_name)
            assert verdict.state != STATE_DONE_IDLE, where
            if verdict.tier == TIER_PANE:
                assert verdict.state == STATE_NEEDS_USER, where


def test_rule_b_a_single_quiet_pane_read_never_retires_a_needs_user():
    named_question = _evidence(
        registry=_registry(REG_WAITING, waiting_for=WAITING_INPUT_NEEDED),
        transcript=_turn_open(blocked_on_tool="AskUserQuestion"),
    )
    assert resolve_attention(named_question).state == STATE_NEEDS_USER
    with_clear_pane = resolve_attention(
        _evidence(
            registry=named_question.registry,
            transcript=named_question.transcript,
            pane=PANE_CLEAR,
        )
    )
    _assert_verdict(with_clear_pane, STATE_NEEDS_USER, REASON_QUESTION, TIER_TRANSCRIPT)

    vetoed = resolve_attention(
        _evidence(
            registry=_registry(REG_WAITING, waiting_for=WAITING_PERMISSION_PROMPT),
            transcript=_at_rest(pending=0),
            pane=PANE_CLEAR,
        )
    )
    _assert_verdict(vetoed, STATE_UNKNOWN, REASON_EVIDENCE_DISAGREES, TIER_REGISTRY)


def test_rule_c_a_registry_record_about_a_previous_run_may_never_originate_done_idle():
    perfect_transcript = _at_rest(pending=0, quiet=10.0)

    previous_run = resolve_attention(
        _evidence(registry=REGISTRY_STALE, transcript=perfect_transcript)
    )
    _assert_verdict(previous_run, STATE_UNKNOWN, REASON_REGISTRY_STALE, TIER_REGISTRY)

    inside = resolve_attention(
        _evidence(
            registry=_registry(
                REG_IDLE, status_age=REGISTRY_STALE_AFTER_SECONDS - 1
            ),
            transcript=perfect_transcript,
        )
    )
    assert inside.state == STATE_DONE_IDLE


def test_a_stale_idle_registry_with_transcript_corroboration_reaches_done_idle():
    for hours in (37.3, 98.5):
        verdict = resolve_attention(
            _evidence(
                registry=_registry(REG_IDLE, status_age=hours * 3600.0),
                transcript=_at_rest(pending=0, quiet=hours * 3600.0),
            )
        )
        where = "an idle stamp %.1fh old" % hours
        _assert_verdict(verdict, STATE_DONE_IDLE, REASON_TURN_ENDED, TIER_REGISTRY)
        assert verdict.pending_background_agents == 0, where
        assert verdict.settle_required is False, where
        assert "corroborates" in verdict.detail, where
        assert (
            to_display(verdict, unread=False, tmux_status=STATUS_RUNNING)
            == STATUS_IDLE
        ), where


@pytest.mark.parametrize(
    "name, transcript",
    [
        ("no turn-end record", _facts(FACTS_NO_RECORD)),
        ("transcript unreadable", _facts(FACTS_UNREADABLE)),
        ("turn still open at EOF", _turn_open(quiet=STREAMING_LOOKBACK_SECONDS + 60)),
    ],
)
def test_a_stale_idle_registry_with_no_corroboration_still_answers_registry_stale(
    name, transcript
):
    verdict = resolve_attention(
        _evidence(
            registry=_registry(
                REG_IDLE, status_age=REGISTRY_STALE_AFTER_SECONDS + 1
            ),
            transcript=transcript,
        )
    )

    _assert_verdict(verdict, STATE_UNKNOWN, REASON_REGISTRY_STALE, TIER_REGISTRY)
    assert verdict.state != STATE_DONE_IDLE, name
    assert to_display(verdict, unread=False, tmux_status=STATUS_RUNNING) == (
        STATUS_UNKNOWN
    )


@pytest.mark.parametrize("version", ["2.1.240", "2.0.999", "", "nightly", None])
def test_corroboration_with_an_untrusted_version_never_reaches_done_idle(version):
    registry = _registry(
        REG_IDLE, version=version, status_age=REGISTRY_STALE_AFTER_SECONDS + 1
    )
    assert registry.trusts_pending_count is False

    verdict = resolve_attention(
        _evidence(registry=registry, transcript=_at_rest(pending=0, quiet=37.3 * 3600))
    )

    _assert_verdict(verdict, STATE_UNKNOWN, REASON_REGISTRY_STALE, TIER_REGISTRY)
    assert verdict.pending_background_agents is None


def test_a_stale_waiting_registry_still_sustains_needs_user():
    for waiting_for, reason in (
        (WAITING_INPUT_NEEDED, REASON_INPUT),
        (WAITING_PERMISSION_PROMPT, REASON_PERMISSION),
    ):
        verdict = resolve_attention(
            _evidence(
                registry=_registry(
                    REG_WAITING,
                    waiting_for=waiting_for,
                    status_age=98.5 * 3600.0,
                ),
                transcript=_at_rest(pending=0, quiet=98.5 * 3600.0),
            )
        )
        where = "a %s waiting stamp 98.5h old" % waiting_for
        _assert_verdict(verdict, STATE_NEEDS_USER, reason, TIER_REGISTRY)
        assert verdict.state != STATE_DONE_IDLE, where


@pytest.mark.parametrize(
    "version", ["2.1.240", "2.0.999", "2.1.266-beta.1", "", "nightly", None, 2.1]
)
def test_rule_d_an_untrusted_version_never_reaches_done_idle_and_uses_the_ledger(
    version,
):
    registry = _registry(REG_IDLE, version=version)
    assert registry.verdict == REG_OK
    assert registry.trusts_pending_count is False

    refused = resolve_attention(
        _evidence(registry=registry, transcript=_at_rest(pending=0))
    )
    _assert_verdict(refused, STATE_UNKNOWN, REASON_NO_EVIDENCE, TIER_REGISTRY)
    assert refused.pending_background_agents is None

    ledgered = resolve_attention(
        _evidence(
            registry=registry,
            transcript=_at_rest(pending=0, open_async_agents=2),
        )
    )
    _assert_verdict(ledgered, STATE_BUSY, REASON_SUBAGENTS, TIER_TRANSCRIPT)

    uncounted = resolve_attention(
        _evidence(registry=registry, transcript=_at_rest(pending=4))
    )
    assert uncounted.state == STATE_UNKNOWN
    assert uncounted.pending_background_agents is None


@pytest.mark.parametrize("family", ["hermes", "gemini", "aider", "cursor"])
def test_rule_e_a_non_claude_family_never_reaches_done_idle_through_the_registry(
    family,
):
    perfect = dict(
        registry=_registry(REG_IDLE), transcript=_at_rest(pending=0, quiet=10.0)
    )

    refused = resolve_attention(_evidence(family=family, **perfect))
    _assert_verdict(refused, STATE_UNKNOWN, REASON_NO_EVIDENCE, TIER_NONE)
    assert family in refused.detail

    on_screen = resolve_attention(
        _evidence(family=family, pane=PANE_PERMISSION, **perfect)
    )
    _assert_verdict(on_screen, STATE_NEEDS_USER, REASON_PERMISSION, TIER_PANE)
    assert on_screen.settle_required is True

    assert resolve_attention(_evidence(family=None, **perfect)).state == STATE_DONE_IDLE
    assert (
        resolve_attention(_evidence(family=FAMILY_CLAUDE, **perfect)).state
        == STATE_DONE_IDLE
    )



THE_EIGHT = frozenset(
    {
        STATUS_DEAD,
        STATUS_QUESTION,
        STATUS_NOTICE,
        STATUS_WORKING,
        STATUS_WORKING_SUBAGENT,
        STATUS_FINISHED_UNREAD,
        STATUS_IDLE,
        STATUS_UNKNOWN,
    }
)

DISPLAY_TABLE = [
    (STATE_UNKNOWN, REASON_PANE_DEAD, STATUS_DEAD),
    (STATE_NEEDS_USER, REASON_QUESTION, STATUS_QUESTION),
    (STATE_NEEDS_USER, REASON_PERMISSION, STATUS_QUESTION),
    (STATE_NEEDS_USER, REASON_PLAN_APPROVAL, STATUS_QUESTION),
    (STATE_NEEDS_USER, REASON_INPUT, STATUS_NOTICE),
    (STATE_BUSY, REASON_SUBAGENTS, STATUS_WORKING_SUBAGENT),
    (STATE_BUSY, REASON_QUEUED_REINVOKE, STATUS_WORKING_SUBAGENT),
    (STATE_BUSY, REASON_STREAMING, STATUS_WORKING),
    (STATE_BUSY, REASON_TOOL, STATUS_WORKING),
    (STATE_UNKNOWN, REASON_REGISTRY_ABSENT, STATUS_UNKNOWN),
    (STATE_UNKNOWN, REASON_REGISTRY_STALE, STATUS_UNKNOWN),
    (STATE_UNKNOWN, REASON_REGISTRY_UNREADABLE, STATUS_UNKNOWN),
    (STATE_UNKNOWN, REASON_SHAPE_UNRECOGNIZED, STATUS_UNKNOWN),
    (STATE_UNKNOWN, REASON_EVIDENCE_DISAGREES, STATUS_UNKNOWN),
    (STATE_UNKNOWN, REASON_NO_EVIDENCE, STATUS_UNKNOWN),
    (STATE_UNKNOWN, REASON_AMBIGUOUS_PANE, STATUS_UNKNOWN),
    (STATE_UNKNOWN, REASON_RESTING_PROMPT, STATUS_UNKNOWN),
    (STATE_UNKNOWN, REASON_STARTING, STATUS_UNKNOWN),
]


def test_to_display_maps_every_verdict_onto_one_of_the_eight_and_invents_no_ninth():
    for state, reason, expected in DISPLAY_TABLE:
        verdict = AttentionVerdict(state=state, reason=reason, tier=TIER_REGISTRY)
        for unread in (True, False):
            painted = to_display(verdict, unread=unread, tmux_status=STATUS_RUNNING)
            assert painted == expected, "%s(%s) unread=%s" % (state, reason, unread)

    at_rest = AttentionVerdict(
        state=STATE_DONE_IDLE, reason=REASON_TURN_ENDED, tier=TIER_REGISTRY
    )
    assert to_display(at_rest, unread=True, tmux_status=STATUS_RUNNING) == (
        STATUS_FINISHED_UNREAD
    )
    assert to_display(at_rest, unread=False, tmux_status=STATUS_RUNNING) == STATUS_IDLE

    painted = {
        to_display(
            AttentionVerdict(state=state, reason=reason, tier=TIER_REGISTRY),
            unread=unread,
            tmux_status=tmux_status,
        )
        for state in ALL_STATES
        for reason in ALL_REASONS
        for unread in (True, False)
        for tmux_status in (STATUS_RUNNING, STATUS_IDLE, STATUS_DEAD, STATUS_UNKNOWN)
    }
    assert painted <= THE_EIGHT

    assert {reason for _, reason, _ in DISPLAY_TABLE} | {REASON_TURN_ENDED} == (
        ALL_REASONS
    )


def test_an_unknown_verdict_borrows_nothing_from_tmux_except_death():
    refused = AttentionVerdict(
        state=STATE_UNKNOWN, reason=REASON_NO_EVIDENCE, tier=TIER_NONE
    )

    assert to_display(refused, unread=False, tmux_status=STATUS_IDLE) == STATUS_UNKNOWN
    assert to_display(refused, unread=True, tmux_status=STATUS_IDLE) == STATUS_UNKNOWN
    assert to_display(refused, unread=False, tmux_status=STATUS_DEAD) == STATUS_DEAD




def test_every_tier_absent_answers_unknown_and_never_done_idle():
    verdict = resolve_attention(
        Evidence(
            tmux_liveness=LIVENESS_UNKNOWN,
            agent_family=None,
            registry=REGISTRY_ABSENT,
            transcript=_facts(FACTS_UNREADABLE),
            pane=None,
            now=NOW,
        )
    )

    _assert_verdict(verdict, STATE_UNKNOWN, REASON_REGISTRY_ABSENT, TIER_REGISTRY)
    assert verdict.pending_background_agents is None
    assert to_display(verdict, unread=True, tmux_status=STATUS_RUNNING) == STATUS_UNKNOWN


@pytest.mark.parametrize(
    "status_age",
    [600.0, REGISTRY_STALE_AFTER_SECONDS + 1, 98.5 * 3600.0],
)
def test_a_stale_busy_contradicted_by_a_newer_at_rest_transcript_disagrees(status_age):
    verdict = resolve_attention(
        _evidence(
            registry=_registry(REG_BUSY, status_age=status_age),
            transcript=_at_rest(pending=0, quiet=30.0),
        )
    )

    _assert_verdict(verdict, STATE_UNKNOWN, REASON_EVIDENCE_DISAGREES, TIER_REGISTRY)

    assert verdict.state != STATE_BUSY
    assert verdict.state != STATE_DONE_IDLE


def test_an_all_blank_pane_is_none_not_false_and_decides_nothing():
    assert PANE_BLANK.permission_dialog is None
    assert PANE_BLANK.question_dialog is None
    assert PANE_BLANK.trust_dialog is None
    assert PANE_BLANK.looked is False
    assert PANE_BLANK.shows_dialog is False
    assert PANE_BLANK.shows_no_dialog is False

    believed = resolve_attention(
        _evidence(
            registry=_registry(REG_WAITING, waiting_for=WAITING_INPUT_NEEDED),
            transcript=_at_rest(),
            pane=PANE_BLANK,
        )
    )
    _assert_verdict(believed, STATE_NEEDS_USER, REASON_INPUT, TIER_REGISTRY)

    toward_the_human = resolve_attention(
        _evidence(
            registry=_registry(REG_WAITING, waiting_for=WAITING_INPUT_NEEDED),
            transcript=_turn_open(),
            pane=PANE_BLANK,
        )
    )
    _assert_verdict(
        toward_the_human, STATE_NEEDS_USER, REASON_PERMISSION, TIER_TRANSCRIPT
    )

    read_and_clear = resolve_attention(
        _evidence(
            registry=_registry(REG_WAITING, waiting_for=WAITING_INPUT_NEEDED),
            transcript=_at_rest(),
            pane=PANE_CLEAR,
        )
    )
    assert read_and_clear.reason == REASON_EVIDENCE_DISAGREES


def test_a_transcript_with_no_record_is_never_read_as_zero_pending_agents():
    absent_count = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE),
            transcript=_at_rest(pending=None, pending_field_present=False),
        )
    )
    assert absent_count.state != STATE_DONE_IDLE
    assert absent_count.pending_background_agents is None

    unwritten = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE),
            transcript=_facts(FACTS_NO_RECORD, newest_append_at=NOW - timedelta(seconds=30)),
        )
    )
    assert unwritten.state != STATE_DONE_IDLE
    assert unwritten.pending_background_agents is None

    zero_without_a_record = resolve_attention(
        _evidence(
            registry=_registry(REG_IDLE),
            transcript=_facts(
                FACTS_NO_RECORD,
                pending_background_agents=0,
                pending_field_present=True,
                turn_end_at=NOW - timedelta(seconds=30),
                newest_append_at=NOW - timedelta(seconds=30),
            ),
        )
    )
    assert zero_without_a_record.state != STATE_DONE_IDLE

    assert (
        resolve_attention(
            _evidence(registry=_registry(REG_IDLE), transcript=_at_rest(pending=0))
        ).state
        == STATE_DONE_IDLE
    )




def test_settle_is_required_for_pane_and_eof_decided_verdicts():
    cases = [
        (
            "the pane showed a dialog",
            _evidence(
                registry=_registry(REG_WAITING, waiting_for=WAITING_INPUT_NEEDED),
                transcript=_at_rest(),
                pane=PANE_PERMISSION,
            ),
        ),
        (
            "the transcript ends on a blocking tool",
            _evidence(
                registry=_registry(REG_WAITING, waiting_for=WAITING_INPUT_NEEDED),
                transcript=_turn_open(blocked_on_tool="AskUserQuestion"),
            ),
        ),
        (
            "the turn is open at EOF and the pane could not be read",
            _evidence(
                registry=_registry(REG_WAITING, waiting_for=WAITING_INPUT_NEEDED),
                transcript=_turn_open(),
                pane=None,
            ),
        ),
        (
            "no registry, and the transcript ends on a blocking tool",
            _evidence(transcript=_turn_open(blocked_on_tool="ExitPlanMode")),
        ),
        (
            "another family, dialog on screen",
            _evidence(family="hermes", pane=PANE_QUESTION),
        ),
    ]
    for name, evidence in cases:
        assert resolve_attention(evidence).settle_required is True, name


def test_settle_is_not_required_for_registry_decided_verdicts():
    cases = [
        ("done_idle", _evidence(registry=_registry(REG_IDLE), transcript=_at_rest())),
        (
            "busy streaming",
            _evidence(
                registry=_registry(REG_BUSY, status_age=1.0), transcript=_at_rest()
            ),
        ),
        (
            "busy tool",
            _evidence(
                registry=_registry(REG_BUSY, status_age=1.0), transcript=_turn_open()
            ),
        ),
        (
            "waiting, named",
            _evidence(
                registry=_registry(REG_WAITING, waiting_for=WAITING_SANDBOX_REQUEST),
                transcript=_at_rest(),
            ),
        ),
        (
            "busy on background agents",
            _evidence(registry=_registry(REG_IDLE), transcript=_at_rest(pending=5)),
        ),
        (
            "queued re-invoke",
            _evidence(
                registry=_registry(REG_IDLE),
                transcript=_at_rest(queued_reinvoke=True),
            ),
        ),
        ("pane gone", _evidence(tmux_liveness=LIVENESS_GONE)),
        ("no evidence at all", _evidence()),
        (
            "evidence disagrees",
            _evidence(
                registry=_registry(REG_BUSY, status_age=600.0),
                transcript=_at_rest(quiet=30.0),
            ),
        ),
    ]
    for name, evidence in cases:
        assert resolve_attention(evidence).settle_required is False, name


@pytest.mark.parametrize("status", [REG_IDLE, REG_BUSY, REG_WAITING])
@pytest.mark.parametrize("pane,reason", [
    (PANE_PERMISSION, REASON_PERMISSION), (PANE_QUESTION, REASON_QUESTION),
])
def test_live_dialog_outranks_background_work_for_every_registry_status(status, pane, reason):
    verdict = resolve_attention(_evidence(
        registry=_registry(status),
        transcript=_at_rest(pending=2, open_async_agents=1, queued_reinvoke=True),
        pane=pane,
    ))
    _assert_verdict(verdict, STATE_NEEDS_USER, reason, TIER_PANE)
    assert verdict.settle_required is True

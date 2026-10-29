
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    REASON_REGISTRY_ABSENT,
    REASON_SUBAGENTS,
    REASON_TURN_ENDED,
    STATE_BUSY,
    STATE_DONE_IDLE,
    STATE_UNKNOWN,
    TIER_REGISTRY,
    TIER_TRANSCRIPT,
    Evidence,
)
from src.core.attention.registry_record import (
    REG_IDLE,
    REGISTRY_STALE_AFTER_SECONDS,
    parse_registry_record,
)
from src.core.attention.registry_index import registry_for_session
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import (
    FACTS_FOUND,
    FACTS_NO_RECORD,
    FACTS_UNREADABLE,
    TURN_END_INTERRUPT,
    TURN_END_NO_MODEL_TURN,
    TranscriptFacts,
    read_transcript_facts,
)
from src.core.session_status import LIVENESS_LIVE

SESSION_UUID = "0b7c4a52-5d0e-4a8b-9d53-6f0f3c2e9a11"
CWD = "/Users/alex/cloude-projects/ses_rest_shapes"
TMUX_NAME = "cloude_rest-shapes"

NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)


def _ts(seconds_before_now: float) -> str:
    at = NOW - timedelta(seconds=seconds_before_now)
    return at.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (at.microsecond // 1000)


def _base(kind: str, seconds_before_now: float) -> Dict[str, Any]:
    return {
        "parentUuid": "5e1c0a9e-6c7b-4d0f-8a39-0f3a5d8e2b41",
        "isSidechain": False,
        "type": kind,
        "timestamp": _ts(seconds_before_now),
        "uuid": "a4f9e3d2-1b0c-4e5f-9a8b-7c6d5e4f3a2b",
        "userType": "external",
        "entrypoint": "cli",
        "cwd": CWD,
        "sessionId": SESSION_UUID,
        "version": "2.1.266",
        "gitBranch": "master",
    }


def _interrupt(seconds_before_now: float, *, for_tool_use: bool = False) -> Dict[str, Any]:
    record = _base("user", seconds_before_now)
    record["promptId"] = "3f2e1d0c-9b8a-4765-8f4e-3d2c1b0a9f8e"
    text = "[Request interrupted by user for tool use]"
    if not for_tool_use:
        text = "[Request interrupted by user]"
        record["interruptedMessageId"] = "msg_01SynthesizedInterruptId"
    record["message"] = {"role": "user", "content": [{"type": "text", "text": text}]}
    return record


def _turn_end(seconds_before_now: float) -> Dict[str, Any]:
    record = _base("system", seconds_before_now)
    record.update({"subtype": "turn_duration", "durationMs": 4200, "isMeta": False})
    return record


def _prompt(seconds_before_now: float) -> Dict[str, Any]:
    record = _base("user", seconds_before_now)
    record["promptId"] = "7a6b5c4d-3e2f-4a1b-8c9d-0e1f2a3b4c5d"
    record["message"] = {"role": "user", "content": "keep going"}
    return record


def _assistant_text(seconds_before_now: float) -> Dict[str, Any]:
    record = _base("assistant", seconds_before_now)
    record["message"] = {
        "role": "assistant",
        "content": [{"type": "text", "text": "working on it"}],
    }
    return record


def _assistant_tool_use(seconds_before_now: float, tool_use_id: str, name: str = "Bash") -> Dict[str, Any]:
    record = _base("assistant", seconds_before_now)
    record["message"] = {
        "role": "assistant",
        "stop_reason": "tool_use",
        "content": [
            {"type": "tool_use", "id": tool_use_id, "name": name, "input": {}}
        ],
    }
    return record


def _tool_result(seconds_before_now: float, tool_use_id: str) -> Dict[str, Any]:
    record = _base("user", seconds_before_now)
    record["toolUseResult"] = "done"
    record["message"] = {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": "done"}
        ],
    }
    return record


def _agent_launch(seconds_before_now: float, task_id: str, tool_use_id: str) -> Dict[str, Any]:
    record = _base("user", seconds_before_now)
    record["toolUseResult"] = {
        "isAsync": True,
        "status": "async_launched",
        "agentId": task_id,
        "description": "Research",
        "outputFile": "/tmp/" + task_id + ".output",
    }
    record["message"] = {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": "Agent started"}
        ],
    }
    return record


def _caveat(seconds_before_now: float) -> Dict[str, Any]:
    record = _base("user", seconds_before_now)
    record["isMeta"] = True
    record["message"] = {
        "role": "user",
        "content": "<local-command-caveat>Caveat: synthesized.</local-command-caveat>",
    }
    return record


def _command(seconds_before_now: float, name: str) -> Dict[str, Any]:
    record = _base("user", seconds_before_now)
    record["message"] = {
        "role": "user",
        "content": "<command-name>/%s</command-name>\n            "
        "<command-message>%s</command-message>\n            "
        "<command-args></command-args>" % (name, name),
    }
    return record


def _stdout(seconds_before_now: float) -> Dict[str, Any]:
    record = _base("user", seconds_before_now)
    record["message"] = {
        "role": "user",
        "content": "<local-command-stdout>ok</local-command-stdout>",
    }
    return record


def _system_local_command(seconds_before_now: float, content: str) -> Dict[str, Any]:
    record = _base("system", seconds_before_now)
    record.update(
        {"subtype": "local_command", "content": content, "level": "info", "isMeta": False}
    )
    return record


def _expanding_command(seconds_before_now: float) -> Dict[str, Any]:
    record = _base("user", seconds_before_now)
    record["message"] = {
        "role": "user",
        "content": "<command-message>review</command-message>\n"
        "<command-name>/review</command-name>",
    }
    return record


def _write(tmp_path, records: List[Dict[str, Any]], name: str = "t.jsonl") -> str:
    path = tmp_path / name
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return str(path)


def _registry_idle(status_age: float = 10.0):
    payload = {
        "sessionId": SESSION_UUID,
        "cwd": CWD,
        "pid": 51292,
        "startedAt": 1789095742551,
        "version": "2.1.266",
        "kind": "interactive",
        "entrypoint": "cli",
        "tmux": TMUX_NAME + ":@205.%205",
        "status": "idle",
        "updatedAt": int((NOW - timedelta(seconds=status_age)).timestamp() * 1000),
        "statusUpdatedAt": int((NOW - timedelta(seconds=status_age)).timestamp() * 1000),
    }
    return parse_registry_record(payload, path_pid=None)


def _resolve(facts: TranscriptFacts, registry: Optional[Any] = None):
    return resolve_attention(
        Evidence(
            tmux_liveness=LIVENESS_LIVE,
            agent_family=FAMILY_CLAUDE,
            registry=registry if registry is not None else _registry_idle(),
            transcript=facts,
            pane=None,
            now=NOW,
        )
    )


def _earlier_turn() -> List[Dict[str, Any]]:
    return [
        _prompt(600),
        _assistant_text(590),
        _turn_end(589),
        _prompt(120),
        _assistant_tool_use(110, "toolu_01Aa"),
        _tool_result(100, "toolu_01Aa"),
        _assistant_text(90),
    ]




@pytest.mark.parametrize("for_tool_use", [False, True])
def test_an_interrupt_is_a_turn_end_with_nothing_pending(tmp_path, for_tool_use):
    path = _write(tmp_path, _earlier_turn() + [_interrupt(60, for_tool_use=for_tool_use)])
    facts = read_transcript_facts(path, now=NOW)

    assert facts.verdict == FACTS_FOUND
    assert facts.turn_end_kind == TURN_END_INTERRUPT
    assert facts.turn_end_at == NOW - timedelta(seconds=60)
    assert facts.pending_background_agents == 0
    assert facts.pending_workflows == 0
    assert facts.pending_field_present is False

    verdict = _resolve(facts)
    assert (verdict.state, verdict.reason, verdict.tier) == (
        STATE_DONE_IDLE,
        REASON_TURN_ENDED,
        TIER_REGISTRY,
    )
    assert "interrupt" in verdict.detail


def test_an_interrupt_with_no_earlier_turn_end_in_the_window_is_still_rest(tmp_path):
    records = [
        _prompt(300),
        _assistant_tool_use(290, "toolu_01Bb"),
        _tool_result(70, "toolu_01Bb"),
        _interrupt(65),
    ]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.turn_end_kind == TURN_END_INTERRUPT
    assert facts.pending_background_agents == 0
    assert _resolve(facts).state == STATE_DONE_IDLE


def test_a_stale_idle_stamp_over_an_interrupt_takes_the_corroborated_path(tmp_path):
    days = 30 * 86400.0
    records = [
        _prompt(days + 300),
        _assistant_tool_use(days + 290, "toolu_01Cc"),
        _tool_result(days + 5, "toolu_01Cc"),
        _interrupt(days),
    ]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    verdict = _resolve(facts, _registry_idle(status_age=days - 0.001))
    assert verdict.state == STATE_DONE_IDLE
    assert "corroborates" in verdict.detail


def test_a_local_command_after_an_interrupt_keeps_it_rest(tmp_path):
    records = _earlier_turn() + [
        _interrupt(60),
        _caveat(50),
        _command(50, "rename"),
        _stdout(49),
    ]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.turn_end_kind == TURN_END_INTERRUPT
    assert _resolve(facts).state == STATE_DONE_IDLE


def test_a_turn_duration_after_an_interrupt_is_the_turn_end(tmp_path):
    records = _earlier_turn() + [_interrupt(60), _turn_end(59)]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.turn_end_kind == "turn_duration"
    assert facts.turn_end_at == NOW - timedelta(seconds=59)




@pytest.mark.parametrize(
    "tail",
    [
        pytest.param([_prompt(30)], id="new-prompt"),
        pytest.param([_expanding_command(30)], id="expanding-slash-command"),
        pytest.param([_prompt(30), _assistant_text(20)], id="new-prompt-and-answer"),
    ],
)
def test_an_interrupt_followed_by_new_input_is_not_rest(tmp_path, tail):
    records = [
        _prompt(300),
        _assistant_tool_use(290, "toolu_01Dd"),
        _tool_result(70, "toolu_01Dd"),
        _interrupt(65),
    ] + tail
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.turn_end_kind != TURN_END_INTERRUPT
    assert _resolve(facts).state != STATE_DONE_IDLE


def test_an_assistant_record_after_an_interrupt_is_not_rest(tmp_path):
    records = _earlier_turn() + [_interrupt(60), _assistant_text(30)]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert _resolve(facts).state != STATE_DONE_IDLE


def test_an_interrupt_over_an_open_background_agent_is_working(tmp_path):
    records = [
        _prompt(300),
        _assistant_tool_use(290, "toolu_01Ee", name="Agent"),
        _agent_launch(289, "a1b2c3d4", "toolu_01Ee"),
        _assistant_text(200),
        _interrupt(60),
    ]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.open_async_agents == 1
    verdict = _resolve(facts)
    assert (verdict.state, verdict.reason, verdict.tier) == (
        STATE_BUSY,
        REASON_SUBAGENTS,
        TIER_TRANSCRIPT,
    )


def test_an_interrupt_inherits_a_positive_count_from_the_turn_end_before_it(tmp_path):
    counted = _turn_end(200)
    counted["pendingBackgroundAgentCount"] = 2
    records = [_prompt(300), _assistant_text(290), counted, _prompt(120), _assistant_text(100), _interrupt(60)]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.pending_background_agents == 2
    assert _resolve(facts).state == STATE_BUSY


def test_an_interrupt_over_a_tool_call_nothing_answered_is_not_rest(tmp_path):
    records = [
        _prompt(300),
        _assistant_tool_use(290, "toolu_01Ff"),
        _interrupt(60),
    ]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.turn_end_kind != TURN_END_INTERRUPT
    assert _resolve(facts).state != STATE_DONE_IDLE


def test_a_sidechain_interrupt_is_not_the_main_turn_ending(tmp_path):
    side = _interrupt(60)
    side["isSidechain"] = True
    records = [_prompt(300), _assistant_tool_use(290, "toolu_01Gg"), _tool_result(70, "toolu_01Gg"), side]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.verdict == FACTS_NO_RECORD
    assert _resolve(facts).state != STATE_DONE_IDLE


def test_interrupt_text_inside_a_longer_prompt_is_not_an_interrupt(tmp_path):
    quoted = _prompt(60)
    quoted["message"]["content"] = "why did it say [Request interrupted by user] there"
    records = [_prompt(300), _assistant_text(290), quoted]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.verdict == FACTS_NO_RECORD




def test_a_conversation_of_only_local_slash_commands_is_rest(tmp_path):
    records = [
        _caveat(120),
        _command(120, "clear"),
        _system_local_command(119, "<local-command-stdout></local-command-stdout>"),
        _caveat(60),
        _command(60, "model"),
        _stdout(59),
    ]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)

    assert facts.verdict == FACTS_FOUND
    assert facts.turn_end_kind == TURN_END_NO_MODEL_TURN
    assert facts.turn_end_at == NOW - timedelta(seconds=59)
    assert facts.pending_background_agents == 0
    assert facts.pending_workflows == 0
    assert facts.newest_assistant_at is None

    verdict = _resolve(facts)
    assert (verdict.state, verdict.reason, verdict.tier) == (
        STATE_DONE_IDLE,
        REASON_TURN_ENDED,
        TIER_REGISTRY,
    )
    assert "no model turn" in verdict.detail


def test_system_local_command_records_alone_are_rest(tmp_path):
    records = [
        _system_local_command(60, "<command-name>/rename</command-name>\n            <command-message>rename</command-message>\n            <command-args></command-args>"),
        _system_local_command(59, "<local-command-stdout>ok</local-command-stdout>"),
    ]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.turn_end_kind == TURN_END_NO_MODEL_TURN
    assert _resolve(facts).state == STATE_DONE_IDLE




@pytest.mark.parametrize(
    "extra",
    [
        pytest.param(_prompt(30), id="typed-prompt-awaiting-reply"),
        pytest.param(_expanding_command(30), id="expanding-slash-command"),
    ],
)
def test_a_prompt_with_no_reply_yet_is_not_a_conversation_at_rest(tmp_path, extra):
    records = [_caveat(120), _command(120, "clear"), _stdout(119), extra]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.verdict == FACTS_NO_RECORD
    assert _resolve(facts).state != STATE_DONE_IDLE


def test_a_slash_command_window_that_is_not_the_whole_file_is_not_rest(tmp_path):
    records = [_prompt(900), _assistant_text(890)]
    records += [_system_local_command(600 - i, "<local-command-stdout>" + "x" * 400 + "</local-command-stdout>") for i in range(40)]
    path = _write(tmp_path, records)
    facts = read_transcript_facts(path, tail_bytes=4096, wide_tail_bytes=4096, now=NOW)
    assert facts.newest_assistant_at is None, "the window must exclude the assistant"
    assert facts.verdict == FACTS_NO_RECORD
    assert _resolve(facts).state != STATE_DONE_IDLE


def test_a_window_with_only_bookkeeping_is_not_rest(tmp_path):
    records = [{"type": "mode", "mode": "normal", "sessionId": SESSION_UUID}]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.verdict == FACTS_NO_RECORD




def test_an_unreadable_transcript_stays_unknown(tmp_path):
    facts = read_transcript_facts(str(tmp_path / "missing.jsonl"), now=NOW)
    assert facts.verdict == FACTS_UNREADABLE
    assert _resolve(facts).state == STATE_UNKNOWN


@pytest.mark.parametrize(
    "records",
    [
        pytest.param([_prompt(300), _assistant_tool_use(290, "toolu_01Hh"), _tool_result(70, "toolu_01Hh"), _interrupt(65)], id="interrupt"),
        pytest.param([_caveat(120), _command(120, "clear"), _stdout(119)], id="no-model-turn"),
    ],
)
def test_no_registry_record_is_never_rest(tmp_path, records):
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.verdict == FACTS_FOUND
    absent = registry_for_session(tmux_name=TMUX_NAME, index={})
    verdict = _resolve(facts, absent)
    assert (verdict.state, verdict.reason) == (STATE_UNKNOWN, REASON_REGISTRY_ABSENT)


def test_an_untrusted_registry_version_is_never_rest_over_an_interrupt(tmp_path):
    records = [_prompt(300), _assistant_tool_use(290, "toolu_01Ii"), _tool_result(70, "toolu_01Ii"), _interrupt(65)]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    registry = _registry_idle()
    old = parse_registry_record(
        dict(
            sessionId=SESSION_UUID, cwd=CWD, pid=51292, startedAt=1789095742551,
            version="2.1.240", kind="interactive", entrypoint="cli",
            tmux=TMUX_NAME + ":@205.%205", status="idle",
            updatedAt=int(NOW.timestamp() * 1000) - 10000,
            statusUpdatedAt=int(NOW.timestamp() * 1000) - 10000,
        ),
        path_pid=None,
    )
    assert registry.trusts_pending_count and not old.trusts_pending_count
    assert _resolve(facts, old).state != STATE_DONE_IDLE


def test_the_stale_horizon_constant_is_unchanged():
    assert REGISTRY_STALE_AFTER_SECONDS == 900
    assert REG_IDLE == "idle"


def _interrupted_turn_after(prior_count: int, filler_bytes: int, calls: int) -> List[Dict[str, Any]]:
    counted = _turn_end(900)
    counted["pendingBackgroundAgentCount"] = prior_count
    records = [
        _prompt(1000),
        _assistant_tool_use(990, "toolu_bg", "Task"),
        _agent_launch(989, "a1b2c3", "toolu_bg"),
        _assistant_text(950),
        counted,
        _prompt(300),
    ]
    for i in range(calls):
        tool_use_id = "toolu_%02d" % i
        records.append(_assistant_tool_use(250 - i, tool_use_id, "Read"))
        result = _tool_result(249 - i, tool_use_id)
        result["message"]["content"][0]["content"] = "x" * filler_bytes
        records.append(result)
    records.append(_interrupt(60))
    return records


def test_an_interrupt_whose_turn_end_scrolled_out_keeps_the_agent_working(tmp_path):
    path = _write(tmp_path, _interrupted_turn_after(1, 40000, 10))
    facts = read_transcript_facts(path, now=NOW)
    assert facts.pending_background_agents == 1
    assert _resolve(facts).state == STATE_BUSY


def test_an_interrupt_whose_zero_turn_end_scrolled_out_is_still_rest(tmp_path):
    path = _write(tmp_path, _interrupted_turn_after(0, 40000, 8))
    facts = read_transcript_facts(path, now=NOW)
    assert facts.turn_end_kind == TURN_END_INTERRUPT
    assert facts.pending_background_agents == 0
    assert _resolve(facts).state == STATE_DONE_IDLE


def test_an_interrupt_with_no_turn_end_even_in_the_wide_window_is_not_rest(tmp_path):
    path = _write(tmp_path, _interrupted_turn_after(0, 10000, 10))
    facts = read_transcript_facts(path, now=NOW, tail_bytes=4096, wide_tail_bytes=32768)
    assert facts.turn_end_kind == TURN_END_INTERRUPT
    assert facts.pending_background_agents is None
    assert _resolve(facts).state != STATE_DONE_IDLE


def test_a_partial_window_interrupt_with_no_turn_end_has_no_count():
    from src.core.attention.transcript_facts import classify_transcript_records

    records = [_prompt(300), _assistant_text(100), _interrupt(60)]
    partial = classify_transcript_records(records, window_is_whole_file=False)
    whole = classify_transcript_records(records, window_is_whole_file=True)
    assert partial.pending_background_agents is None
    assert partial.pending_workflows is None
    assert whole.pending_background_agents == 0


def _completion_enqueued(seconds_before_now: float, task_id: str, tool_use_id: str) -> Dict[str, Any]:
    record = _base("queue-operation", seconds_before_now)
    record["operation"] = "enqueue"
    record["content"] = (
        "<task-notification>\n<task-id>" + task_id + "</task-id>\n<tool-use-id>"
        + tool_use_id + "</tool-use-id>\n<status>completed</status>\n</task-notification>"
    )
    return record


def test_an_interrupt_after_a_counted_agent_finished_is_unknown_not_working(tmp_path):
    counted = _turn_end(900)
    counted["pendingBackgroundAgentCount"] = 1
    records = [
        _prompt(1000),
        _assistant_tool_use(990, "toolu_bg", "Task"),
        _agent_launch(989, "a1b2c3", "toolu_bg"),
        _assistant_text(950),
        counted,
        _completion_enqueued(880, "a1b2c3", "toolu_bg"),
        _assistant_text(870),
        _assistant_tool_use(860, "toolu_01Zz", "Read"),
        _tool_result(70, "toolu_01Zz"),
        _interrupt(65),
    ]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.turn_end_kind == TURN_END_INTERRUPT
    assert facts.pending_background_agents is None
    assert _resolve(facts).state == STATE_UNKNOWN


def test_a_task_that_ended_does_not_disturb_an_inherited_zero(tmp_path):
    records = [
        _prompt(1000), _assistant_text(950), _turn_end(900),
        _completion_enqueued(880, "a9", "toolu_old"),
        _prompt(300), _assistant_text(100), _interrupt(60),
    ]
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)
    assert facts.pending_background_agents == 0

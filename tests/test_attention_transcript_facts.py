
from __future__ import annotations

import json

import pytest
from typing import Any, Dict, List, Optional

from src.core.attention.transcript_facts import (
    BLOCKING_TOOL_NAMES,
    BOOKKEEPING_RECORD_TYPES,
    FACTS_FOUND,
    FACTS_NO_RECORD,
    FACTS_TAIL_BYTES,
    FACTS_UNREADABLE,
    classify_transcript_records,
    read_transcript_facts,
)
from src.core.claude_title_sync import DEFAULT_TAIL_BYTES

SESSION_UUID = "ea5fcd7e-c297-4f63-8740-170403025cdd"
CWD = "/Users/example/marridge-elmwick/belford_marridge"


def _turn_end(
    timestamp: str, pending: Any = "omit", version: Optional[str] = "2.1.266"
) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "parentUuid": "61425be1-a6dc-48be-87af-e500076acf02",
        "isSidechain": False,
        "type": "system",
        "subtype": "turn_duration",
        "durationMs": 75930,
        "messageCount": 56,
        "timestamp": timestamp,
        "uuid": "6b09440b-7e65-4fae-84b4-0dce91b930c0",
        "isMeta": False,
        "userType": "external",
        "entrypoint": "cli",
        "cwd": CWD,
        "sessionId": SESSION_UUID,
        "version": "2.1.266",
        "gitBranch": "master",
        "slug": "reactive-foraging-dream",
    }
    if pending != "omit":
        record["pendingBackgroundAgentCount"] = pending
    if version is None:
        del record["version"]
    else:
        record["version"] = version
    return record


def _assistant_tool_use(
    timestamp: str, name: str, tool_use_id: str
) -> Dict[str, Any]:
    return {
        "type": "assistant",
        "isSidechain": False,
        "timestamp": timestamp,
        "sessionId": SESSION_UUID,
        "message": {
            "role": "assistant",
            "stop_reason": "tool_use",
            "content": [
                {"type": "text", "text": "let me ask"},
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": name,
                    "input": {"questions": []},
                },
            ],
        },
    }


def _tool_result(timestamp: str, tool_use_id: str) -> Dict[str, Any]:
    return {
        "type": "user",
        "isSidechain": False,
        "timestamp": timestamp,
        "sessionId": SESSION_UUID,
        "toolUseResult": "Your questions have been answered: yes",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": "Your questions have been answered: yes",
                }
            ],
        },
    }


def _notification_body(task_id: str, tool_use_id: str) -> str:
    return (
        "<task-notification>\n"
        "<task-id>" + task_id + "</task-id>\n"
        "<tool-use-id>" + tool_use_id + "</tool-use-id>\n"
        "<status>completed</status>\n"
        '<summary>Agent "Research" finished</summary>\n'
        "</task-notification>"
    )


def _enqueue(timestamp: str, task_id: str, tool_use_id: str) -> Dict[str, Any]:
    return {
        "type": "queue-operation",
        "operation": "enqueue",
        "timestamp": timestamp,
        "sessionId": SESSION_UUID,
        "content": _notification_body(task_id, tool_use_id),
    }


def _async_launch(
    timestamp: str, task_id: str, tool_use_id: str
) -> Dict[str, Any]:
    return {
        "type": "user",
        "isSidechain": False,
        "timestamp": timestamp,
        "sessionId": SESSION_UUID,
        "toolUseResult": {
            "isAsync": True,
            "status": "async_launched",
            "agentId": task_id,
            "description": "Research",
            "outputFile": "/tmp/" + task_id + ".output",
        },
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": "Agent started",
                }
            ],
        },
    }


def _task_notification(
    timestamp: str, task_id: str, tool_use_id: str
) -> Dict[str, Any]:
    return {
        "type": "user",
        "isSidechain": False,
        "timestamp": timestamp,
        "sessionId": SESSION_UUID,
        "origin": {"kind": "task-notification"},
        "promptSource": "system",
        "message": {
            "role": "user",
            "content": _notification_body(task_id, tool_use_id),
        },
    }


def _user_prompt(timestamp: str, text: str = "keep going") -> Dict[str, Any]:
    return {
        "type": "user",
        "isSidechain": False,
        "timestamp": timestamp,
        "sessionId": SESSION_UUID,
        "message": {"role": "user", "content": text},
    }


def _write(tmp_path, records: List[Any], torn_tail: Optional[str] = None) -> str:
    path = tmp_path / (SESSION_UUID + ".jsonl")
    body = "".join(json.dumps(record) + "\n" for record in records)
    if torn_tail is not None:
        body += torn_tail
    path.write_text(body, encoding="utf-8")
    return str(path)


def _bookkeeping(kind: str, **fields: Any) -> Dict[str, Any]:
    record: Dict[str, Any] = {"type": kind, "sessionId": SESSION_UUID}
    record.update(fields)
    return record


_SOAK_HIDDEN_QUESTION_TAIL: List[Dict[str, Any]] = [
    _assistant_tool_use(
        "2026-09-13T22:57:49.950Z", "AskUserQuestion", "toolu_01H0Yejme4ueSo2nywIux0ab"
    ),
    _bookkeeping(
        "queue-operation",
        operation="enqueue",
        timestamp="2026-09-13T22:57:55.975Z",
        content="<task-notification>\n<task-id>46dfa6e79aae20074</task-id>\n",
    ),
    _bookkeeping(
        "queue-operation",
        operation="enqueue",
        timestamp="2026-09-13T23:01:14.631Z",
        content="check the archive",
    ),
    _bookkeeping(
        "queue-operation",
        operation="remove",
        timestamp="2026-09-13T23:01:14.695Z",
        content="check the archive",
        reason="delivered_to_agent",
    ),
    _bookkeeping(
        "queue-operation",
        operation="enqueue",
        timestamp="2026-09-13T23:01:19.178Z",
        content="and then stop",
    ),
    _bookkeeping(
        "last-prompt",
        lastPrompt="Do exactly two things in this one turn, in this order.",
        leafUuid="5017575e-a56f-4475-8558-a51456fd08c8",
    ),
    _bookkeeping("cost-state", totalCostUSD=0.82638125, hasUnknownModelCost=False),
]


_RESUME_BURST_HIDDEN_QUESTION_TAIL: List[Dict[str, Any]] = [
    _assistant_tool_use("2026-09-13T18:00:10.000Z", "AskUserQuestion", "toolu_q"),
    _bookkeeping("last-prompt", lastPrompt="Firford this", leafUuid="08ed14bb"),
    _bookkeeping("custom-title", customTitle="TEAM-Docs"),
    _bookkeeping("agent-name", agentName="TEAM-Docs"),
    _bookkeeping("mode", mode="normal"),
    _bookkeeping("permission-mode", permissionMode="auto"),
    _bookkeeping("atis-latch", atis=""),
    _bookkeeping("bridge-session", bridgeSessionId="cse_01Nc7I5jzWDj5OsUF309EoNP"),
]


_ANSWERED_THEN_BOOKKEEPING_TAIL: List[Dict[str, Any]] = [
    _assistant_tool_use("2026-09-13T22:54:49.237Z", "AskUserQuestion", "toolu_a"),
    _tool_result("2026-09-13T22:56:38.141Z", "toolu_a"),
    {
        "type": "attachment",
        "timestamp": "2026-09-13T22:56:38.144Z",
        "sessionId": SESSION_UUID,
        "attachment": {"type": "output_style", "style": "Metal Hacker"},
    },
    _bookkeeping("last-prompt", lastPrompt="ask me one question", leafUuid="7ed4b2ac"),
    _bookkeeping("custom-title", customTitle="ZZVAL2"),
    _bookkeeping("agent-name", agentName="ZZVAL2"),
    _bookkeeping("mode", mode="normal"),
    _bookkeeping("permission-mode", permissionMode="auto"),
    _bookkeeping("bridge-session", bridgeSessionId="cse_01Nc7I5jzWDj5OsUF309EoNP"),
]




def test_turn_end_with_one_pending_agent_reports_one():
    facts = classify_transcript_records(
        [_turn_end("2026-09-13T18:30:58.233Z", pending=1)]
    )
    assert facts.verdict == FACTS_FOUND
    assert facts.found is True
    assert facts.pending_background_agents == 1
    assert facts.pending_field_present is True


def test_turn_end_with_three_pending_agents_reports_three():
    facts = classify_transcript_records(
        [_turn_end("2026-09-13T18:30:58.233Z", pending=3)]
    )
    assert facts.pending_background_agents == 3
    assert facts.pending_field_present is True


def test_pending_count_of_json_null_is_unknown_because_none_was_ever_written():
    facts = classify_transcript_records(
        [_turn_end("2026-09-13T18:30:58.233Z", pending=None)]
    )
    assert facts.verdict == FACTS_FOUND
    assert facts.pending_background_agents is None
    assert facts.pending_field_present is True


def test_an_omitted_pending_field_at_or_above_the_version_floor_is_zero():
    facts = classify_transcript_records(
        [_turn_end("2026-09-13T18:30:58.233Z", version="2.1.266")]
    )
    assert facts.verdict == FACTS_FOUND
    assert facts.pending_background_agents == 0
    assert facts.pending_field_present is False


def test_an_omitted_pending_field_at_the_version_floor_itself_is_zero():
    facts = classify_transcript_records(
        [_turn_end("2026-09-13T18:30:58.233Z", version="2.1.241")]
    )
    assert facts.pending_background_agents == 0


def test_an_omitted_pending_field_below_the_version_floor_is_unknown():
    facts = classify_transcript_records(
        [_turn_end("2026-09-13T18:30:58.233Z", version="2.1.240")]
    )
    assert facts.verdict == FACTS_FOUND
    assert facts.pending_background_agents is None
    assert facts.pending_field_present is False


def test_an_omitted_pending_field_with_no_readable_version_is_unknown():
    for version in (None, "2.1.266-beta.1"):
        facts = classify_transcript_records(
            [_turn_end("2026-09-13T18:30:58.233Z", version=version)]
        )
        assert facts.pending_background_agents is None, version


def test_the_version_that_counts_is_the_one_on_the_turn_end_record():
    facts = classify_transcript_records(
        [
            _turn_end("2026-09-13T18:00:00.000Z", version="2.1.266"),
            _turn_end("2026-09-13T18:10:00.000Z", version="2.1.240"),
        ]
    )
    assert facts.pending_background_agents is None

    facts = classify_transcript_records(
        [
            _turn_end("2026-09-13T18:00:00.000Z", version="2.1.240"),
            _turn_end("2026-09-13T18:10:00.000Z", version="2.1.266"),
        ]
    )
    assert facts.pending_background_agents == 0


def test_an_omitted_count_and_a_missing_record_are_not_the_same_answer():
    omitted = classify_transcript_records(
        [_turn_end("2026-09-13T18:30:58.233Z", version="2.1.266")]
    )
    none_at_all = classify_transcript_records(
        [_assistant_tool_use("2026-09-13T18:30:58.233Z", "Bash", "toolu_a")]
    )

    assert omitted.verdict == FACTS_FOUND
    assert omitted.pending_background_agents == 0
    assert none_at_all.verdict == FACTS_NO_RECORD
    assert none_at_all.pending_background_agents is None
    assert none_at_all.turn_end_at is None


def test_a_pending_count_that_is_not_a_number_is_unknown_and_says_so():
    facts = classify_transcript_records(
        [_turn_end("2026-09-13T18:30:58.233Z", pending="lots")]
    )
    assert facts.pending_background_agents is None
    assert facts.pending_field_present is True
    assert "not a number" in facts.detail


def test_a_window_with_no_turn_end_record_refuses_rather_than_reporting_zero():
    facts = classify_transcript_records(
        [
            _user_prompt("2026-09-13T18:00:00.000Z"),
            _assistant_tool_use("2026-09-13T18:00:01.000Z", "Bash", "toolu_a"),
        ]
    )
    assert facts.verdict == FACTS_NO_RECORD
    assert facts.pending_background_agents is None
    assert facts.pending_field_present is False


def test_the_newest_turn_end_record_in_the_window_is_the_one_that_counts():
    facts = classify_transcript_records(
        [
            _turn_end("2026-09-13T18:00:00.000Z", pending=3),
            _user_prompt("2026-09-13T18:05:00.000Z"),
            _turn_end("2026-09-13T18:10:00.000Z"),
        ]
    )
    assert facts.pending_background_agents == 0
    assert facts.turn_end_at is not None
    assert facts.turn_end_at.hour == 18 and facts.turn_end_at.minute == 10




def test_a_window_ending_on_an_unanswered_ask_user_question_names_the_tool():
    facts = classify_transcript_records(
        [
            _turn_end("2026-09-13T18:00:00.000Z", pending=None),
            _assistant_tool_use(
                "2026-09-13T18:00:10.000Z", "AskUserQuestion", "toolu_q"
            ),
        ]
    )
    assert facts.blocked_on_tool == "AskUserQuestion"


def test_a_window_ending_on_an_unanswered_exit_plan_mode_names_the_tool():
    facts = classify_transcript_records(
        [
            _assistant_tool_use(
                "2026-09-13T18:00:10.000Z", "ExitPlanMode", "toolu_p"
            )
        ]
    )
    assert facts.blocked_on_tool == "ExitPlanMode"
    assert "ExitPlanMode" in BLOCKING_TOOL_NAMES


def test_an_answered_question_is_not_blocking_any_more():
    facts = classify_transcript_records(
        [
            _assistant_tool_use(
                "2026-09-13T18:00:10.000Z", "AskUserQuestion", "toolu_q"
            ),
            _tool_result("2026-09-13T18:01:00.000Z", "toolu_q"),
        ]
    )
    assert facts.blocked_on_tool is None


def test_a_running_tool_at_the_end_of_the_window_is_not_a_question():
    facts = classify_transcript_records(
        [_assistant_tool_use("2026-09-13T18:00:10.000Z", "Bash", "toolu_b")]
    )
    assert facts.blocked_on_tool is None
    assert "still running" in facts.detail




def test_the_soak_failure_queue_operations_after_a_question_still_name_it():
    facts = classify_transcript_records(_SOAK_HIDDEN_QUESTION_TAIL)
    assert facts.blocked_on_tool == "AskUserQuestion"
    assert "waiting on the user" in facts.detail


def test_every_record_of_that_real_tail_hides_the_question_one_at_a_time():
    for end in range(2, len(_SOAK_HIDDEN_QUESTION_TAIL) + 1):
        facts = classify_transcript_records(_SOAK_HIDDEN_QUESTION_TAIL[:end])
        assert facts.blocked_on_tool == "AskUserQuestion", end


def test_the_real_resume_burst_after_a_question_still_names_it():
    facts = classify_transcript_records(_RESUME_BURST_HIDDEN_QUESTION_TAIL)
    assert facts.blocked_on_tool == "AskUserQuestion"


def test_a_real_mode_record_after_an_exit_plan_mode_does_not_answer_it():
    facts = classify_transcript_records(
        [
            _assistant_tool_use(
                "2026-09-13T18:00:10.000Z", "ExitPlanMode", "toolu_p"
            ),
            _bookkeeping("mode", mode="normal"),
            _bookkeeping("permission-mode", permissionMode="auto"),
            _bookkeeping("bridge-session", bridgeSessionId="cse_01Fs"),
        ]
    )
    assert facts.blocked_on_tool == "ExitPlanMode"


def test_an_answered_question_stays_answered_behind_the_same_bookkeeping():
    facts = classify_transcript_records(_ANSWERED_THEN_BOOKKEEPING_TAIL)
    assert facts.blocked_on_tool is None


def test_every_record_of_the_answered_tail_keeps_the_question_closed():
    for end in range(2, len(_ANSWERED_THEN_BOOKKEEPING_TAIL) + 1):
        facts = classify_transcript_records(_ANSWERED_THEN_BOOKKEEPING_TAIL[:end])
        assert facts.blocked_on_tool is None, end


def test_a_system_record_after_a_question_is_not_skipped():
    facts = classify_transcript_records(
        [
            _assistant_tool_use(
                "2026-09-13T18:00:10.000Z", "AskUserQuestion", "toolu_q"
            ),
            _turn_end("2026-09-13T18:00:20.000Z", pending=None),
        ]
    )
    assert facts.blocked_on_tool is None


def test_an_attachment_after_a_question_is_skipped_since_2026_09_18():
    facts = classify_transcript_records(
        [
            _assistant_tool_use(
                "2026-09-13T18:00:10.000Z", "AskUserQuestion", "toolu_q"
            ),
            {"type": "attachment", "timestamp": "2026-09-13T18:00:20.000Z"},
        ]
    )
    assert facts.blocked_on_tool == "AskUserQuestion"


def test_an_attachment_over_an_ANSWERED_question_still_answers_none():
    facts = classify_transcript_records(
        [
            _assistant_tool_use(
                "2026-09-13T18:00:10.000Z", "AskUserQuestion", "toolu_q"
            ),
            _tool_result("2026-09-13T18:00:15.000Z", "toolu_q"),
            {"type": "attachment", "timestamp": "2026-09-13T18:00:20.000Z"},
        ]
    )
    assert facts.blocked_on_tool is None


def test_an_answer_anywhere_in_the_window_refuses_the_question():
    facts = classify_transcript_records(
        [
            _assistant_tool_use(
                "2026-09-13T18:00:10.000Z", "AskUserQuestion", "toolu_q"
            ),
            _tool_result("2026-09-13T18:01:00.000Z", "toolu_q"),
            _assistant_tool_use(
                "2026-09-13T18:02:00.000Z", "AskUserQuestion", "toolu_q"
            ),
            _bookkeeping("queue-operation", operation="enqueue", content="later"),
        ]
    )
    assert facts.blocked_on_tool is None


def test_bookkeeping_at_the_end_never_invents_a_question_on_its_own():
    facts = classify_transcript_records(
        [
            _assistant_tool_use("2026-09-13T18:00:10.000Z", "Bash", "toolu_b"),
            _bookkeeping("cost-state", totalCostUSD=0.82638125),
        ]
    )
    assert facts.blocked_on_tool is None


def test_the_skip_set_holds_no_conversational_type():
    assert not BOOKKEEPING_RECORD_TYPES & {"user", "assistant", "system"}




def test_an_enqueued_notification_newer_than_the_turn_end_is_a_queued_reinvoke():
    facts = classify_transcript_records(
        [
            _turn_end("2026-09-13T18:25:11.174Z", pending=1),
            _enqueue("2026-09-13T18:25:58.808Z", "ac21bf29", "toolu_01"),
        ]
    )
    assert facts.queued_reinvoke is True


def test_an_enqueued_notification_older_than_the_turn_end_is_not_one():
    facts = classify_transcript_records(
        [
            _enqueue("2026-09-13T18:20:00.000Z", "ac21bf29", "toolu_01"),
            _turn_end("2026-09-13T18:25:11.174Z", pending=None),
        ]
    )
    assert facts.queued_reinvoke is False


def test_three_launches_with_two_completions_leave_one_agent_open():
    facts = classify_transcript_records(
        [
            _async_launch("2026-09-13T18:00:01.000Z", "task_a", "toolu_a"),
            _async_launch("2026-09-13T18:00:02.000Z", "task_b", "toolu_b"),
            _async_launch("2026-09-13T18:00:03.000Z", "task_c", "toolu_c"),
            _task_notification("2026-09-13T18:10:00.000Z", "task_a", "toolu_a"),
            _task_notification("2026-09-13T18:11:00.000Z", "task_b", "toolu_b"),
        ]
    )
    assert facts.open_async_agents == 1


def test_a_completion_whose_launch_is_behind_the_window_never_goes_negative():
    facts = classify_transcript_records(
        [_task_notification("2026-09-13T18:10:00.000Z", "task_z", "toolu_z")]
    )
    assert facts.open_async_agents == 0




def test_a_typed_prompt_is_the_newest_user_prompt():
    facts = classify_transcript_records(
        [_user_prompt("2026-09-13T18:00:00.000Z")]
    )
    assert facts.newest_user_prompt_at is not None


def test_a_task_notification_is_not_the_user_showing_up():
    facts = classify_transcript_records(
        [_task_notification("2026-09-13T18:10:00.000Z", "task_a", "toolu_a")]
    )
    assert facts.newest_user_prompt_at is None


def test_a_tool_result_is_not_the_user_showing_up():
    facts = classify_transcript_records(
        [_tool_result("2026-09-13T18:10:00.000Z", "toolu_q")]
    )
    assert facts.newest_user_prompt_at is None


def test_a_sub_agents_own_prompt_is_not_the_user_showing_up():
    sidechain = _user_prompt("2026-09-13T18:10:00.000Z")
    sidechain["isSidechain"] = True
    facts = classify_transcript_records([sidechain])
    assert facts.newest_user_prompt_at is None


def test_the_newest_append_is_the_newest_record_of_any_type():
    facts = classify_transcript_records(
        [
            _user_prompt("2026-09-13T18:00:00.000Z"),
            _turn_end("2026-09-13T18:30:00.000Z", pending=None),
        ]
    )
    assert facts.newest_append_at is not None
    assert facts.newest_append_at.minute == 30


def test_the_newest_assistant_record_is_reported_apart_from_the_turn_end():
    facts = classify_transcript_records(
        [
            _assistant_tool_use("2026-09-13T18:00:00.000Z", "Bash", "toolu_b"),
            _turn_end("2026-09-13T18:30:00.000Z", pending=None),
        ]
    )
    assert facts.newest_assistant_at is not None
    assert facts.newest_assistant_at.minute == 0
    assert facts.turn_end_at is not None
    assert facts.turn_end_at.minute == 30


def test_junk_entries_in_the_window_are_tolerated():
    facts = classify_transcript_records(
        ["not a record", 7, None, _turn_end("2026-09-13T18:30:00.000Z", pending=2)]
    )
    assert facts.pending_background_agents == 2




def test_a_torn_final_line_still_reads_the_good_records_before_it(tmp_path):
    path = _write(
        tmp_path,
        [
            _user_prompt("2026-09-13T18:00:00.000Z"),
            _turn_end("2026-09-13T18:30:00.000Z", pending=2),
        ],
        torn_tail='{"type":"system","subtype":"turn_dur',
    )
    facts = read_transcript_facts(path)
    assert facts.verdict == FACTS_FOUND
    assert facts.pending_background_agents == 2


def test_a_real_file_reads_the_same_facts_as_the_pure_classifier(tmp_path):
    records = [
        _turn_end("2026-09-13T18:25:11.174Z", pending=1),
        _enqueue("2026-09-13T18:25:58.808Z", "task_a", "toolu_a"),
    ]
    path = _write(tmp_path, records)
    assert read_transcript_facts(path) == classify_transcript_records(records)


def test_a_missing_transcript_is_unreadable_and_not_an_absence_of_work(tmp_path):
    facts = read_transcript_facts(str(tmp_path / "nothing-here.jsonl"))
    assert facts.verdict == FACTS_UNREADABLE
    assert facts.detail


def test_no_path_at_all_is_unreadable():
    assert read_transcript_facts(None).verdict == FACTS_UNREADABLE


def test_an_empty_transcript_holds_no_record_rather_than_refusing_to_read(tmp_path):
    path = _write(tmp_path, [])
    facts = read_transcript_facts(path)
    assert facts.verdict == FACTS_NO_RECORD


def test_this_caller_widens_its_own_window_and_leaves_the_shared_one_alone():
    assert FACTS_TAIL_BYTES == 256 * 1024
    assert DEFAULT_TAIL_BYTES == 64 * 1024




def test_neither_an_empty_window_nor_a_missing_file_claims_the_turn_ended(tmp_path):
    empty = classify_transcript_records([])
    missing = read_transcript_facts(str(tmp_path / "gone.jsonl"))

    for facts in (empty, missing):
        assert facts.verdict != FACTS_FOUND
        assert facts.found is False
        assert facts.pending_background_agents is None
        assert facts.pending_field_present is False
        assert facts.turn_end_at is None
        assert facts.open_async_agents == 0
        assert facts.queued_reinvoke is False
        assert facts.blocked_on_tool is None

    assert empty.verdict == FACTS_NO_RECORD
    assert missing.verdict == FACTS_UNREADABLE
    assert empty.verdict != missing.verdict


def test_the_positive_control_proves_the_reader_can_go_green(tmp_path):
    path = _write(
        tmp_path,
        [
            _async_launch("2026-09-13T18:00:01.000Z", "task_a", "toolu_a"),
            _turn_end("2026-09-13T18:30:00.000Z", pending=1),
        ],
    )
    facts = read_transcript_facts(path)
    assert facts.verdict == FACTS_FOUND
    assert facts.found is True
    assert facts.pending_background_agents == 1
    assert facts.pending_field_present is True
    assert facts.turn_end_at is not None
    assert facts.open_async_agents == 1


def test_a_blocking_record_wider_than_the_window_is_still_the_answer(tmp_path):
    fat = _assistant_tool_use("2026-09-13T18:00:10.000Z", "ExitPlanMode", "toolu_fat")
    fat["message"]["content"][1]["input"] = {"plan": "p" * 40_000}
    path = _write(tmp_path, [_user_prompt("2026-09-13T18:00:00.000Z"), fat])

    facts = read_transcript_facts(path, tail_bytes=32 * 1024)

    assert facts.blocked_on_tool == "ExitPlanMode"


@pytest.mark.parametrize("pending,version", [(0, "2.1.266"), ("omit", "2.1.266")])
def test_zero_pending_boundary_retires_only_earlier_launches(pending, version):
    before = _async_launch("2026-09-13T18:00:01.000Z", "old", "tool_old")
    boundary = _turn_end("2026-09-13T18:00:02.000Z", pending, version)
    after = _async_launch("2026-09-13T18:00:03.000Z", "new", "tool_new")
    assert classify_transcript_records([before, boundary]).open_async_agents == 0
    facts = classify_transcript_records([
        before, boundary, after,
        _enqueue("2026-09-13T18:00:04.000Z", "old", "tool_old"),
    ])
    assert facts.open_async_agents == 1
    assert facts.queued_reinvoke is True


@pytest.mark.parametrize("pending,version", [
    (1, "2.1.266"), (None, "2.1.266"), ("omit", None),
    ("omit", "2.1.240"), (True, "2.1.266"), (-1, "2.1.266"),
])
def test_unreliable_or_positive_count_preserves_unmatched_launch(pending, version):
    facts = classify_transcript_records([
        _async_launch("2026-09-13T18:00:01.000Z", "old", "tool_old"),
        _turn_end("2026-09-13T18:00:02.000Z", pending, version),
    ])
    assert facts.open_async_agents == 1


def test_zero_boundary_still_applies_before_later_unknown_turn_end():
    facts = classify_transcript_records([
        _async_launch("2026-09-13T18:00:01.000Z", "old", "tool_old"),
        _turn_end("2026-09-13T18:00:02.000Z", 0),
        _turn_end("2026-09-13T18:00:03.000Z", None),
    ])
    assert facts.open_async_agents == 0
    assert facts.pending_background_agents is None


from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src.core.attention.transcript_facts import FACTS_FOUND, FACTS_NO_RECORD, classify_transcript_records
from src.core.claude_title_sync import read_tail_records
from src.core.timeline.facts_adapter import TURN_END_FIELDS, facts_from_state
from tests.python.timeline.fold_fixtures import (
    CONV,
    NO_SKIP,
    NOW,
    TAIL,
    agent_launch as _agent_launch,
    assistant as _assistant,
    at as _at,
    build,
    call as _call,
    differences,
    mcp_removed as _mcp,
    notice as _notice,
    notice_text as _notice_text,
    pad as _pad,
    result as _result,
    shell_launch as _shell_launch,
    turn_end as _turn_end,
    user as _user,
)


def _windowed_records() -> List[Dict[str, Any]]:
    before = [
        _user(1, "start the work"),
        _assistant(2, [_call("t_a", "Agent")]), _agent_launch(3, "t_a", "agent_old"),
        _assistant(4, [_call("t_x", "Bash")]), _shell_launch(5, "t_x", "shell_old"),
    ]
    pads = [_pad(10 + i, i) for i in range(16)]
    window = [
        _user(60, "next step"),
        _assistant(61, [_call("t_b", "Agent")]), _agent_launch(62, "t_b", "agent_new"),
        _assistant(63, [_call("t_y", "Bash")]), _shell_launch(64, "t_y", "shell_new"),
        _assistant(65, [_call("t_c", "Agent")]), _agent_launch(66, "t_c", "agent_done"),
        _notice(67, "agent_done", "t_c"),
        _mcp(68),
        _assistant(69, [{"type": "text", "text": "running the checks"}, _call("t_m", "mcp__demo__tool")]),
        _result(70, "t_m"),
        _turn_end(71, pending=2),
        {"type": "queue-operation", "operation": "enqueue", "timestamp": _at(72), "content": _notice_text("agent_new", "t_b")},
        _assistant(73, [{"type": "text", "text": "which one?"}, _call("t_q", "AskUserQuestion")]),
    ]
    return before + pads + window


def _beyond_records() -> List[Dict[str, Any]]:
    head = [_user(1, "go"), _assistant(2, [_call("t_a", "Agent")]), _agent_launch(3, "t_a", "agent_a"),
            _turn_end(4, pending=1)]
    tail = [_user(50, "again")] + [_pad(60 + i, i) for i in range(20)] + [
        _assistant(90, [_call("t_b", "Agent")]), _agent_launch(91, "t_b", "agent_b"),
        _assistant(92, [_call("t_c", "Bash")]),
    ]
    return head + tail


def _small_records() -> List[Dict[str, Any]]:
    limit = _assistant(30, [{"type": "text", "text": "usage limit reached"}], msg="lim", stop="stop_sequence")
    limit.update({"isApiErrorMessage": True, "apiError": "usage_limit_reached",
                  "quotaLimits": {"status": "rejected", "resetsAt": 4102444800}})
    return [
        _user(1, "do it"), _assistant(2, [_call("t_a", "Agent")]), _agent_launch(3, "t_a", "agent_a"),
        _assistant(4, [_call("t_b", "Bash")]), _result(5, "t_b"),
        _user(6, [{"type": "text", "text": "[Request interrupted by user]"}]),
        _user(7, "retry"), _assistant(8, [{"type": "text", "text": "ok"}], msg="r1", stop="end_turn"),
        {"type": "custom-title", "customTitle": "synthetic title", "sessionId": CONV},
        _turn_end(9, pending=1),
        {"type": "queue-operation", "operation": "enqueue", "timestamp": _at(20), "content": _notice_text("agent_a", "t_a")},
        limit,
    ]


def test_adapter_equals_the_whole_file_classifier_and_the_production_window_reader(tmp_path: Path) -> None:
    for name, records, turn_end_beyond in (("windowed", _windowed_records(), False),
                                           ("beyond", _beyond_records(), True), ("small", _small_records(), False)):
        case = build(tmp_path, name, records)
        whole = classify_transcript_records(records, now=NOW, window_is_whole_file=True)
        got_whole = facts_from_state(case.state, now=NOW)
        assert differences(got_whole, whole, frozenset({"mcp_events"})) == [], f"{name}: whole file"
        window_from = read_tail_records(str(case.path), tail_bytes=TAIL).scanned_from
        legacy, got = case.legacy(), case.fold()
        skip = TURN_END_FIELDS if turn_end_beyond else NO_SKIP
        assert differences(got, legacy, skip) == [], f"{name}: production window from byte {window_from}"
        if name == "windowed":
            assert window_from > 0 and whole.open_async_agents > legacy.open_async_agents
            assert whole.open_background_tasks > legacy.open_background_tasks and legacy.blocked_on_tool == "AskUserQuestion"
        if name == "beyond":
            assert (legacy.verdict, got.verdict) == (FACTS_NO_RECORD, FACTS_FOUND)
        if name == "small":
            assert window_from == 0 and legacy.usage_limit is not None and case.state.title == "synthetic title"

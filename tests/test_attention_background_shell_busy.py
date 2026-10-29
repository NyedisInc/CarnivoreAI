
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from src.core.attention.display import to_display
from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    REASON_RESTING_PROMPT,
    REASON_SUBAGENTS,
    REASON_TURN_ENDED,
    STATE_BUSY,
    STATE_DONE_IDLE,
    STATE_UNKNOWN,
    Evidence,
)
from src.core.attention.pane_markers import classify_pane_tail, detect_resting_prompt
from src.core.attention.registry_record import REG_STALE, parse_registry_record
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import classify_transcript_records
from src.core.session_status import (
    LIVENESS_LIVE,
    STATUS_IDLE,
    STATUS_WORKING_SUBAGENT,
)

SESSION_UUID = "715e906a-51e4-4f34-bcd5-fdab1dff523f"

CAPTURED_REGISTRY: Dict[str, Any] = {
    "pid": 54252,
    "sessionId": SESSION_UUID,
    "cwd": "/Users/alex/cloude-projects/Home",
    "startedAt": 1789922449725,
    "version": "2.1.266",
    "kind": "interactive",
    "entrypoint": "cli",
    "tmux": "carnivore_Home-3:@289.%289",
    "status": "shell",
    "updatedAt": 1790105736039,
    "statusUpdatedAt": 1790105736039,
}

OBSERVED_AT = datetime(2026, 9, 22, 19, 40, tzinfo=timezone.utc)


def _record(kind: str, timestamp: str, **fields: Any) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "type": kind,
        "isSidechain": False,
        "timestamp": timestamp,
        "sessionId": SESSION_UUID,
    }
    record.update(fields)
    return record


def _turn_end(timestamp: str) -> Dict[str, Any]:
    return _record("system", timestamp, subtype="turn_duration", version="2.1.266")


def _assistant(timestamp: str) -> Dict[str, Any]:
    return _record(
        "assistant",
        timestamp,
        message={"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
    )


def _result(timestamp: str, tool_use_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    return _record(
        "user",
        timestamp,
        toolUseResult=result,
        message={
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": "x"}],
        },
    )


def _shell_launch(timestamp: str, task_id: str, tool_use_id: str) -> Dict[str, Any]:
    return _result(
        timestamp,
        tool_use_id,
        {
            "stdout": "",
            "stderr": "",
            "interrupted": False,
            "isImage": False,
            "noOutputExpected": False,
            "backgroundTaskId": task_id,
        },
    )


def _monitor_launch(timestamp: str, task_id: str, tool_use_id: str) -> Dict[str, Any]:
    return _result(
        timestamp,
        tool_use_id,
        {"taskId": task_id, "timeoutMs": 3600000, "persistent": True},
    )


def _task_stop(timestamp: str, task_id: str, tool_use_id: str) -> Dict[str, Any]:
    return _result(
        timestamp,
        tool_use_id,
        {
            "message": "stopped",
            "task_id": task_id,
            "task_type": "local_bash",
            "command": "tail -f log",
        },
    )


def _notice_text(task_id: str, status: Optional[str], tool_use_id: Optional[str]) -> str:
    parts = ["<task-notification>", "<task-id>" + task_id + "</task-id>"]
    if tool_use_id:
        parts.append("<tool-use-id>" + tool_use_id + "</tool-use-id>")
    if status is None:
        parts.append("<summary>Monitor event</summary>")
        parts.append("<event>a line matched</event>")
    else:
        parts.append("<status>" + status + "</status>")
        parts.append("<summary>Background command finished</summary>")
    parts.append("</task-notification>")
    return "\n".join(parts)


def _notice(
    timestamp: str,
    task_id: str,
    status: Optional[str] = "completed",
    tool_use_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _record(
        "user",
        timestamp,
        origin={"kind": "task-notification"},
        promptSource="system",
        message={"role": "user", "content": _notice_text(task_id, status, tool_use_id)},
    )


def _enqueued_notice(timestamp: str, task_id: str, status: Optional[str] = "completed"):
    return _record(
        "queue-operation",
        timestamp,
        operation="enqueue",
        content=_notice_text(task_id, status, None),
    )


def _attached_notice(timestamp: str, task_id: str, status: Optional[str] = "completed"):
    return _record(
        "attachment",
        timestamp,
        attachment={"type": "queued_command", "prompt": _notice_text(task_id, status, None)},
    )


def _captured_transcript() -> List[Dict[str, Any]]:
    return [
        _assistant("2026-09-22T17:00:26.000Z"),
        _turn_end("2026-09-22T17:00:27.117Z"),
        _monitor_launch("2026-09-22T17:03:00.175Z", "bb0mkq4x2", "toolu_mon1"),
        _assistant("2026-09-22T17:03:24.000Z"),
        _turn_end("2026-09-22T17:03:24.346Z"),
        _enqueued_notice("2026-09-22T18:33:11.918Z", "bb0mkq4x2", None),
        _notice("2026-09-22T18:33:11.943Z", "bb0mkq4x2", None),
        _assistant("2026-09-22T18:34:10.000Z"),
        _turn_end("2026-09-22T18:34:10.362Z"),
        _enqueued_notice("2026-09-22T18:34:12.001Z", "bb0mkq4x2", None),
        _notice("2026-09-22T18:34:12.011Z", "bb0mkq4x2", None),
        _task_stop("2026-09-22T18:35:07.486Z", "bb0mkq4x2", "toolu_stop"),
        _monitor_launch("2026-09-22T18:35:17.654Z", "bom9wqm9y", "toolu_mon2"),
        _assistant("2026-09-22T18:35:23.000Z"),
        _turn_end("2026-09-22T18:35:23.329Z"),
        _assistant("2026-09-22T19:35:35.000Z"),
        _turn_end("2026-09-22T19:35:35.966Z"),
    ]


def _captured_pane(footer: str) -> List[str]:
    rule = "─" * 60
    return [
        "✻ Cogitated for 55s · done 3:35 PM · 1 monitor still running",
        "",
        rule,
        "❯ ",
        rule,
        "  \U0001f4e6/cloude-projects/Home | Opus",
        footer,
    ]


LIVE_FOOTER = "  ⏵⏵ bypass permissions on · 1 monitor · ← 1 agent"
QUIET_FOOTER = "  ⏵⏵ bypass permissions on · ← 1 agent"


def _resolve(records, pane_lines=None, *, registry=None):
    pane = classify_pane_tail(pane_lines) if pane_lines is not None else None
    if registry is None:
        registry = parse_registry_record(dict(CAPTURED_REGISTRY), path_pid=54252)
    return resolve_attention(
        Evidence(
            tmux_liveness=LIVENESS_LIVE,
            agent_family=FAMILY_CLAUDE,
            registry=registry,
            transcript=classify_transcript_records(records),
            pane=pane,
            now=OBSERVED_AT,
            resting_prompt_held=bool(pane is not None and pane.resting_prompt is True),
        )
    )


def _axes(verdict) -> tuple:
    return (verdict.state, verdict.reason, verdict.tier)




def test_a_background_shell_stays_open_across_a_zero_turn_end_until_its_notice():
    launch = _shell_launch("2026-09-22T19:00:00.000Z", "b38bzs3op", "toolu_sh")
    window = [launch, _assistant("2026-09-22T19:00:05.000Z"), _turn_end("2026-09-22T19:00:06.000Z")]
    facts = classify_transcript_records(window)
    assert (facts.pending_background_agents, facts.pending_workflows) == (0, 0)
    assert facts.open_background_tasks == 1
    assert facts.open_async_agents == 0
    done = classify_transcript_records(
        window + [_notice("2026-09-22T19:01:00.000Z", "b38bzs3op", tool_use_id="toolu_sh")]
    )
    assert done.open_background_tasks == 0


def test_a_monitor_stays_open_through_its_event_notices_until_it_is_stopped():
    launch = _monitor_launch("2026-09-22T19:00:00.000Z", "bom9wqm9y", "toolu_mon")
    events = [
        _enqueued_notice("2026-09-22T19:05:00.000Z", "bom9wqm9y", None),
        _notice("2026-09-22T19:05:00.100Z", "bom9wqm9y", None),
        _attached_notice("2026-09-22T19:06:00.000Z", "bom9wqm9y", None),
    ]
    assert classify_transcript_records([launch] + events).open_background_tasks == 1
    stopped = classify_transcript_records(
        [launch] + events + [_task_stop("2026-09-22T19:07:00.000Z", "bom9wqm9y", "toolu_st")]
    )
    assert stopped.open_background_tasks == 0


@pytest.mark.parametrize("status", ["completed", "failed", "killed", "stopped"])
def test_any_status_bearing_notice_retires_a_monitor(status):
    facts = classify_transcript_records(
        [
            _monitor_launch("2026-09-22T19:00:00.000Z", "bom9wqm9y", "toolu_mon"),
            _notice("2026-09-22T19:09:00.000Z", "bom9wqm9y", status),
        ]
    )
    assert facts.open_background_tasks == 0


def test_a_notice_for_a_different_task_does_not_retire_the_launch():
    facts = classify_transcript_records(
        [
            _shell_launch("2026-09-22T19:00:00.000Z", "b38bzs3op", "toolu_sh"),
            _notice("2026-09-22T19:01:00.000Z", "bzzzzzzzz", tool_use_id="toolu_other"),
            _task_stop("2026-09-22T19:02:00.000Z", "byyyyyyyy", "toolu_st"),
        ]
    )
    assert facts.open_background_tasks == 1


@pytest.mark.parametrize("carrier", [_enqueued_notice, _attached_notice])
def test_a_completion_is_read_on_every_record_claude_carries_it_on(carrier):
    facts = classify_transcript_records(
        [
            _shell_launch("2026-09-22T19:00:00.000Z", "b38bzs3op", "toolu_sh"),
            carrier("2026-09-22T19:01:00.000Z", "b38bzs3op"),
        ]
    )
    assert facts.open_background_tasks == 0


def test_the_stopped_notice_claude_writes_on_a_resume_retires_an_orphan():
    facts = classify_transcript_records(
        [
            _shell_launch("2026-09-22T19:00:00.000Z", "b38bzs3op", "toolu_sh"),
            _notice("2026-09-22T20:00:00.000Z", "b38bzs3op", "stopped"),
        ]
    )
    assert facts.open_background_tasks == 0




def test_an_open_background_shell_resolves_working_until_its_completion():
    window = [
        _shell_launch("2026-09-22T19:34:00.000Z", "b38bzs3op", "toolu_sh"),
        _assistant("2026-09-22T19:35:35.000Z"),
        _turn_end("2026-09-22T19:35:35.966Z"),
    ]
    verdict = _resolve(window)
    assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_SUBAGENTS)
    done = _resolve(window + [_notice("2026-09-22T19:36:00.000Z", "b38bzs3op")])
    assert (done.state, done.reason) == (STATE_DONE_IDLE, REASON_TURN_ENDED)


def test_registry_shell_with_no_open_launch_rests_exactly_as_before():
    plain = [_assistant("2026-09-22T19:35:35.000Z"), _turn_end("2026-09-22T19:35:35.966Z")]
    finished = [
        _shell_launch("2026-09-22T19:30:00.000Z", "b38bzs3op", "toolu_sh"),
        _notice("2026-09-22T19:31:00.000Z", "b38bzs3op", tool_use_id="toolu_sh"),
    ] + plain
    baseline = _resolve(plain)
    assert baseline.state == STATE_DONE_IDLE
    assert _axes(_resolve(finished)) == _axes(baseline)
    shown = to_display(baseline, unread=False, tmux_status="running")
    assert shown == STATUS_IDLE


def test_an_open_launch_under_a_refused_registry_record_is_not_counted():
    stale = dataclasses.replace(
        parse_registry_record(dict(CAPTURED_REGISTRY), path_pid=54252), verdict=REG_STALE
    )
    verdict = _resolve(_captured_transcript(), registry=stale)
    assert verdict.state != STATE_BUSY


def test_the_captured_session_resolves_working_not_idle():
    facts = classify_transcript_records(_captured_transcript())
    assert (facts.open_background_tasks, facts.open_async_agents) == (1, 0)
    verdict = _resolve(_captured_transcript(), _captured_pane(LIVE_FOOTER))
    assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_SUBAGENTS)
    shown = to_display(verdict, unread=False, tmux_status="running")
    assert shown == STATUS_WORKING_SUBAGENT


def test_a_resting_pane_with_no_task_pill_still_withdraws_the_claim():
    verdict = _resolve(_captured_transcript(), _captured_pane(QUIET_FOOTER))
    assert (verdict.state, verdict.reason) == (STATE_UNKNOWN, REASON_RESTING_PROMPT)



PILL_FOOTERS = [
    LIVE_FOOTER,
    "  ⏵⏵ bypass permissions on (shift+tab to cycle) · 1 shell",
    "  2 shells, 1 monitor",
    "  3 monitors · ← 1 agent",
    "  ⏸ plan mode on (shift+tab to cycle) · 2 background tasks",
]


@pytest.mark.parametrize("footer", PILL_FOOTERS)
def test_the_task_pill_in_the_footer_refuses_the_resting_claim(footer):
    assert detect_resting_prompt(_captured_pane(footer)) is False


@pytest.mark.parametrize(
    "prompt_line",
    ["❯ · 1 shell", "❯ 2 shells, 1 monitor", "❯ note · 1 monitor · later"],
)
def test_the_same_pill_typed_at_the_prompt_leaves_the_pane_resting(prompt_line):
    lines = _captured_pane(QUIET_FOOTER)
    lines[3] = prompt_line
    assert detect_resting_prompt(lines) is True


def test_the_turn_end_line_naming_a_monitor_leaves_the_pane_resting():
    assert detect_resting_prompt(_captured_pane(QUIET_FOOTER)) is True

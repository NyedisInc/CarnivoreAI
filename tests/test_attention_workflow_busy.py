
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

from src.core.attention.display import to_display
from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    REASON_QUEUED_REINVOKE,
    REASON_RESTING_PROMPT,
    REASON_SUBAGENTS,
    STATE_BUSY,
    STATE_UNKNOWN,
    TIER_PANE,
    TIER_TRANSCRIPT,
    Evidence,
)
from src.core.attention.pane_markers import classify_pane_tail, detect_resting_prompt
from src.core.attention.registry_record import REG_STALE, parse_registry_record
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import (
    FACTS_FOUND,
    TranscriptFacts,
    classify_transcript_records,
)
from src.core.session_status import LIVENESS_LIVE, STATUS_WORKING_SUBAGENT

SESSION_UUID = "62a72065-4220-494c-bdc6-2669b2798f4f"

CAPTURED_REGISTRY: Dict[str, Any] = {
    "pid": 61804,
    "sessionId": SESSION_UUID,
    "cwd": "/Users/alex/Projects/My Projects/Cloude Code Repos/Dev/cloudecode",
    "startedAt": 1790101797207,
    "version": "2.1.280",
    "kind": "interactive",
    "entrypoint": "cli",
    "tmux": "cloude_cloudecode-2:@205.%205",
    "name": "Carnivore-Share",
    "updatedAt": 1790108364182,
    "status": "busy",
    "statusUpdatedAt": 1790108364182,
}

OBSERVED_AT = datetime(2026, 9, 22, 20, 38, tzinfo=timezone.utc)


def _turn_end(timestamp: str, version: str = "2.1.280", **counts: int) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "type": "system",
        "subtype": "turn_duration",
        "isSidechain": False,
        "timestamp": timestamp,
        "sessionId": SESSION_UUID,
        "version": version,
    }
    record.update(counts)
    return record


def _launch_result(timestamp: str, tool_use_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "user",
        "isSidechain": False,
        "timestamp": timestamp,
        "sessionId": SESSION_UUID,
        "toolUseResult": result,
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": "launched"}
            ],
        },
    }


def _workflow_launch(timestamp: str, task_id: str, tool_use_id: str) -> Dict[str, Any]:
    return _launch_result(
        timestamp,
        tool_use_id,
        {
            "status": "async_launched",
            "taskId": task_id,
            "taskType": "local_workflow",
            "workflowName": "ship",
            "runId": "wf_d73a45ac-08c",
            "summary": "merge and verify",
            "transcriptDir": "/tmp/wf",
            "scriptPath": "/tmp/wf/script.js",
        },
    )


def _agent_launch(timestamp: str, agent_id: str, tool_use_id: str) -> Dict[str, Any]:
    return _launch_result(
        timestamp,
        tool_use_id,
        {"isAsync": True, "status": "async_launched", "agentId": agent_id},
    )


def _completion(timestamp: str, task_id: str, tool_use_id: str) -> Dict[str, Any]:
    return {
        "type": "user",
        "isSidechain": False,
        "timestamp": timestamp,
        "sessionId": SESSION_UUID,
        "origin": {"kind": "task-notification"},
        "promptSource": "system",
        "message": {
            "role": "user",
            "content": (
                "<task-notification>\n<task-id>" + task_id + "</task-id>\n"
                "<tool-use-id>" + tool_use_id + "</tool-use-id>\n"
                "<status>completed</status>\n</task-notification>"
            ),
        },
    }


def _assistant(timestamp: str) -> Dict[str, Any]:
    return {
        "type": "assistant",
        "isSidechain": False,
        "timestamp": timestamp,
        "sessionId": SESSION_UUID,
        "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
    }


def _captured_transcript() -> List[Dict[str, Any]]:
    return [
        _workflow_launch("2026-09-22T20:20:20.000Z", "wp7hg6ivq", "toolu_wf"),
        _assistant("2026-09-22T20:20:28.000Z"),
        _turn_end("2026-09-22T20:20:29.085Z", pendingWorkflowCount=1),
        _agent_launch("2026-09-22T20:33:20.000Z", "a15606cae62d85d87", "toolu_ag"),
        _assistant("2026-09-22T20:33:28.000Z"),
        _turn_end(
            "2026-09-22T20:33:28.987Z",
            pendingBackgroundAgentCount=1,
            pendingWorkflowCount=1,
        ),
        _completion("2026-09-22T20:33:46.570Z", "a15606cae62d85d87", "toolu_ag"),
        _assistant("2026-09-22T20:33:49.000Z"),
        _turn_end("2026-09-22T20:33:49.604Z", pendingWorkflowCount=1),
        _assistant("2026-09-22T20:35:19.000Z"),
        _turn_end("2026-09-22T20:35:19.475Z", pendingWorkflowCount=1),
    ]


def _captured_pane(waiting_line: str) -> List[str]:
    rule = "─" * 60
    return [
        "⏺ A diagnosis worker is capturing this session's live status records.",
        "",
        "✻ " + waiting_line,
        "",
        rule + " Carnivore-Share ─",
        "❯ fix it once you confirm the cause",
        rule,
        "  \U0001f4e6/My Projects/Cloude Code Repos/Dev/cloudecode | git:(master) | Opus",
        "  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← 1 agent",
        "",
        "  ⏺ main",
        "  ◯ general-purpose   Diagnose grey status on busy session   13s",
    ]


WAITING_VARIANTS = [
    "Waiting for 1 background agent to finish",
    "Waiting for 3 background agents to finish",
    "Waiting for 1 dynamic workflow to finish",
    "Waiting for 2 dynamic workflows to finish",
    "Waiting for 1 background agent and 1 dynamic workflow to finish",
    "Waiting for 2 background agents and 3 dynamic workflows to finish",
]


def _resolve(records: List[Dict[str, Any]], pane_lines: List[str] = None):
    pane = classify_pane_tail(pane_lines) if pane_lines is not None else None
    return resolve_attention(
        Evidence(
            tmux_liveness=LIVENESS_LIVE,
            agent_family=FAMILY_CLAUDE,
            registry=parse_registry_record(dict(CAPTURED_REGISTRY), path_pid=61804),
            transcript=classify_transcript_records(records),
            pane=pane,
            now=OBSERVED_AT,
            resting_prompt_held=bool(pane is not None and pane.resting_prompt is True),
        )
    )


def test_a_turn_end_with_only_a_pending_workflow_does_not_retire_launches():
    facts = classify_transcript_records(
        [
            _agent_launch("2026-09-22T20:00:00.000Z", "a1", "toolu_a1"),
            _turn_end("2026-09-22T20:00:05.000Z", pendingWorkflowCount=1),
        ]
    )
    assert facts.pending_background_agents == 0
    assert facts.pending_workflows == 1
    assert facts.open_async_agents == 1


def test_a_turn_end_with_only_a_pending_workflow_resolves_busy():
    verdict = _resolve(
        [
            _assistant("2026-09-22T20:35:19.000Z"),
            _turn_end("2026-09-22T20:35:19.475Z", pendingWorkflowCount=1),
        ]
    )
    assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_SUBAGENTS)


def test_a_turn_end_with_both_counts_known_zero_retires_launches():
    facts = classify_transcript_records(
        [
            _agent_launch("2026-09-22T20:00:00.000Z", "a1", "toolu_a1"),
            _workflow_launch("2026-09-22T20:00:01.000Z", "w1", "toolu_w1"),
            _turn_end("2026-09-22T20:00:05.000Z"),
        ]
    )
    assert facts.pending_background_agents == 0
    assert facts.pending_workflows == 0
    assert facts.open_async_agents == 0


def test_an_omitted_workflow_count_below_its_version_floor_is_unknown():
    facts = classify_transcript_records([_turn_end("2026-09-22T20:00:05.000Z", "2.1.230")])
    assert facts.pending_workflows is None


def test_an_async_launched_workflow_is_open_until_its_completion_notice():
    launch = _workflow_launch("2026-09-22T20:20:20.000Z", "wp7hg6ivq", "toolu_wf")
    assert classify_transcript_records([launch]).open_async_agents == 1
    closed = classify_transcript_records(
        [launch, _completion("2026-09-22T20:44:40.785Z", "wp7hg6ivq", "toolu_wf")]
    )
    assert closed.open_async_agents == 0


@pytest.mark.parametrize("wording", WAITING_VARIANTS)
def test_the_waiting_marker_matches_every_wording_claude_composes(wording):
    assert detect_resting_prompt(_captured_pane(wording)) is False


@pytest.mark.parametrize("wording", WAITING_VARIANTS)
def test_the_waiting_marker_does_not_match_the_same_text_typed_at_the_prompt(wording):
    lines = _captured_pane("Cooked for 2m 34s")
    lines[5] = "❯ ✻ " + wording
    assert detect_resting_prompt(lines) is True


@pytest.mark.parametrize(
    "wording",
    [
        "Waiting for 1 dynamic workflow to finish",
        "Waiting for 1 background agent and 1 dynamic workflow to finish",
    ],
)
def test_the_captured_session_resolves_working_not_unknown(wording):
    verdict = _resolve(_captured_transcript(), _captured_pane(wording))
    assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_SUBAGENTS)
    shown = to_display(verdict, unread=False, tmux_status="running")
    assert shown == STATUS_WORKING_SUBAGENT


WORKFLOW_ROWS_PANE = [
    "─────────────────────────────────── example ─",
    "❯ /progress",
    "────────────────────────────────────────────",
    "  \U0001f4e6/example/project | git:(0000000) …",
    "  ⏵⏵ bypass permissions on (shift+tab to",
    "                       ◎ /goal active (4h)",
    "  ◯ workflow-one        ▰▰▰▰▰▰▰▱  ↓ 431.9k",
    "  ◯ workflow-two        ▰▰▰▰▰▰▰▱  ⚠",
]

VETO_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _registry_285(status: str, version: str = "2.1.285"):
    stamped = int((VETO_NOW - timedelta(minutes=40)).timestamp() * 1000)
    return parse_registry_record(
        {
            "pid": 4242,
            "sessionId": SESSION_UUID,
            "cwd": "/example/project",
            "startedAt": stamped - 3600000,
            "procStart": "Mon Sep 29 09:00:00 2026",
            "version": version,
            "peerProtocol": 1,
            "peerFeatures": ["messaging"],
            "kind": "interactive",
            "entrypoint": "cli",
            "pidDomain": "host",
            "tmux": "cloude_example:@1.%1",
            "messagingSocketPath": "/example/claude.sock",
            "name": "Example",
            "nameSource": "flag",
            "nameSince": stamped - 3600000,
            "updatedAt": stamped,
            "status": status,
            "statusUpdatedAt": stamped,
        },
        path_pid=4242,
    )


def _veto_facts(**fields) -> TranscriptFacts:
    end = VETO_NOW - timedelta(minutes=40)
    base = dict(
        pending_background_agents=0,
        pending_field_present=True,
        turn_end_at=end,
        newest_assistant_at=end - timedelta(seconds=1),
        newest_append_at=end,
        detail="the turn ended with work pending",
    )
    base.update(fields)
    return TranscriptFacts(verdict=FACTS_FOUND, **base)


_OPEN_WORKFLOWS = dict(pending_workflows=2, open_async_agents=2)
_BUSY = (STATE_BUSY, REASON_SUBAGENTS, TIER_TRANSCRIPT)
_GREY = (STATE_UNKNOWN, REASON_RESTING_PROMPT, TIER_PANE)


@pytest.mark.parametrize(
    "registry, facts, axes",
    [
        pytest.param(
            _registry_285("busy"), _veto_facts(**_OPEN_WORKFLOWS), _BUSY,
            id="open_workflows_confirmed_by_registry",
        ),
        pytest.param(
            _registry_285("busy"),
            _veto_facts(queued_reinvoke=True, pending_workflows=1, open_async_agents=1),
            (STATE_BUSY, REASON_QUEUED_REINVOKE, TIER_TRANSCRIPT),
            id="queued_follow_up_confirmed_by_registry",
        ),
        pytest.param(
            _registry_285("idle"), _veto_facts(**_OPEN_WORKFLOWS), _GREY,
            id="registry_idle_still_withdrawn",
        ),
        pytest.param(
            _registry_285("busy", "2.1.282"), _veto_facts(**_OPEN_WORKFLOWS), _GREY,
            id="registry_below_the_version_floor_still_withdrawn",
        ),
        pytest.param(
            _registry_285("busy"), _veto_facts(pending_workflows=0), _GREY,
            id="registry_busy_with_nothing_open_still_withdrawn",
        ),
        pytest.param(
            dataclasses.replace(_registry_285("busy"), verdict=REG_STALE),
            _veto_facts(**_OPEN_WORKFLOWS),
            _GREY,
            id="stale_registry_still_withdrawn",
        ),
    ],
)
def test_a_resting_prompt_keeps_background_work_only_when_claudes_record_confirms_it(
    registry, facts, axes
):
    assert detect_resting_prompt(WORKFLOW_ROWS_PANE) is True
    verdict = resolve_attention(
        Evidence(
            tmux_liveness=LIVENESS_LIVE,
            agent_family=FAMILY_CLAUDE,
            registry=registry,
            transcript=facts,
            pane=classify_pane_tail(WORKFLOW_ROWS_PANE),
            now=VETO_NOW,
            resting_prompt_held=True,
        )
    )
    assert (verdict.state, verdict.reason, verdict.tier) == axes, verdict.detail
    if axes[0] == STATE_BUSY:
        assert to_display(verdict, unread=False, tmux_status=None) == (
            STATUS_WORKING_SUBAGENT
        )

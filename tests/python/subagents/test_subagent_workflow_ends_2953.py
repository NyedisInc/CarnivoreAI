
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.subagents import files, stall
from src.core.subagents.reader import read_subagents
from src.core.subagents.stall import read_marked
from src.core.subagents.tally import SubagentTallyCache
from tests.helpers.subagent_fixture import (
    CONV, PROJECT_DIR, _parent, _write_lines, assistant, notification, ts, user,
)

W1, W2, W3, W4, W5, W6 = (f"a{n}00000000000000{n}" for n in range(1, 7))
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
HOME = "/placeholder/.claude/projects/-tmp-fixture-project"


def _epoch(hour: int, minute: int) -> float:
    return datetime(2026, 9, 26, hour, minute, tzinfo=timezone.utc).timestamp()


def _journal(folder: Path, lines: List[Dict[str, Any]], mtime: float) -> None:
    path = folder / "journal.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    os.utime(path, (mtime, mtime))


def _agent(folder: Path, agent_id: str, last: str) -> None:
    (folder / f"agent-{agent_id}.meta.json").write_text(json.dumps(
        {"agentType": "general-purpose", "description": "fixture workflow agent"}))
    _write_lines(folder / f"agent-{agent_id}.jsonl", [user(agent_id, ts(11, 0)), assistant(agent_id, last)])


def _workflow_launch(at: str, task: str, wf: str) -> Dict[str, Any]:
    text = (f"Workflow launched in background. Task ID: {task}\nSummary: placeholder\n"
            f"Transcript dir: {HOME}/{CONV}/subagents/workflows/{wf}\nScript file: /placeholder.js")
    return _parent("user", at, promptId="p", message={"role": "user", "content": [
        {"tool_use_id": "toolu_wf", "type": "tool_result", "content": text}]})


def _workflow_done(task: str, status: str, wf: str | None) -> str:
    block = notification([task], status)
    if wf is None:
        return block
    diag = (f"<diagnostics>Per-agent results: {HOME}/{CONV}/subagents/workflows/{wf}/journal.jsonl"
            " - one result line per completed agent.</diagnostics>")
    return block.replace("</task-notification>", diag + "\n</task-notification>")


@pytest.fixture(autouse=True)
def _fresh():
    files.reset_caches_for_tests()
    yield
    files.reset_caches_for_tests()


@pytest.fixture
def parent(tmp_path) -> Path:
    project = tmp_path / "projects" / PROJECT_DIR
    sub = project / CONV / "subagents" / "workflows"
    wf_x, wf_y, wf_z = (sub / name for name in ("wf_x", "wf_y", "wf_z"))
    for folder in (wf_x, wf_y, wf_z):
        folder.mkdir(parents=True)
    _agent(wf_x, W1, ts(11, 50))
    _agent(wf_x, W2, ts(11, 50))
    _agent(wf_x, W3, ts(11, 50))
    _journal(wf_x, [
        {"type": "launched"},
        {"type": "started", "key": "v2:k1", "agentId": W1},
        {"type": "started", "key": "v2:k2", "agentId": W2},
        {"type": "started", "key": "v2:k3", "agentId": W3},
        {"type": "result", "key": "v2:k1", "agentId": W1, "result": {"claims": []}},
        {"type": "result", "key": "v2:k3", "agentId": W3, "result": None},
    ], _epoch(11, 51))
    _agent(wf_y, W4, ts(11, 50))
    _agent(wf_y, W5, ts(11, 58))
    _journal(wf_y, [{"type": "started", "key": "v2:k4", "agentId": W4},
                    {"type": "started", "key": "v2:k5", "agentId": W5}], _epoch(11, 50))
    _agent(wf_z, W6, ts(11, 50))
    lines = [
        _parent("user", ts(9, 59), promptId="p", message={"role": "user", "content": "placeholder"}),
        _workflow_launch(ts(10, 0), "wfzzz0001", "wf_z"),
        _parent("queue-operation", ts(11, 55), operation="enqueue",
                content=_workflow_done("wtyyy0001", "killed", "wf_y")),
        _parent("queue-operation", ts(11, 56), operation="enqueue",
                content=_workflow_done("wfzzz0001", "completed", None)),
    ]
    transcript = project / f"{CONV}.jsonl"
    _write_lines(transcript, lines)
    return transcript


def _statuses(parent: Path, now: datetime = NOW):
    result = read_subagents(parent, conversation_uuid=CONV, now=now)
    return {row.id: row for row in result.subagents}


def _marks(parent: Path, now: datetime) -> Dict[str, Any]:
    real = stall.conversation_launches
    stall.conversation_launches = lambda _path: []
    try:
        result = read_marked(parent, conversation_uuid=CONV, now=now)
    finally:
        stall.conversation_launches = real
    return {row.id: row.stalled_seconds for row in result.subagents}


def test_a_workflow_agent_with_a_journal_result_is_done_and_a_null_result_is_a_failed_end(parent):
    rows = _statuses(parent)
    assert (rows[W1].status, rows[W1].status_reason, rows[W1].end_status) == ("done", "end_recorded", "completed")
    assert (rows[W3].status, rows[W3].end_status) == ("done", "failed")


def test_a_workflow_agent_with_no_end_anywhere_stays_running_so_a_real_stall_is_caught(parent):
    rows = _statuses(parent)
    assert (rows[W2].status, rows[W2].status_reason) == ("running", "no_end_recorded")
    marks = _marks(parent, NOW)
    assert marks[W2] == 600, "the control agent is quiet 10 minutes and still stalls"
    assert marks[W1] is None and marks[W3] is None


def test_the_workflows_own_notification_ends_every_agent_that_was_quiet_by_then(parent):
    rows = _statuses(parent)
    assert rows[W4].status == "done"
    assert rows[W5].status == "running", "W5 wrote after the notification, so it is not covered"
    assert rows[W6].status == "done", "the launch result mapped task id to wf_z, the notification ended it"


def test_a_finished_workflow_never_reaches_the_notify_list(parent):
    tally = SubagentTallyCache(projects_dir=parent.parents[1]).tally(
        "claude", CONV, None, None, NOW + timedelta(minutes=14))
    notified = {agent.agent_id for agent in tally.long_stalled}
    assert W2 in notified
    assert not notified & {W1, W3, W4, W6}


def test_the_journal_is_reread_when_it_grows(parent):
    folder = parent.parent / CONV / "subagents" / "workflows" / "wf_x"
    assert _statuses(parent)[W2].status == "running"
    with open(folder / "journal.jsonl", "a") as handle:
        handle.write(json.dumps({"type": "result", "key": "v2:k2", "agentId": W2, "result": {}}) + "\n")
    os.utime(folder / "journal.jsonl", (_epoch(11, 53), _epoch(11, 53)))
    assert _statuses(parent)[W2].status == "done"

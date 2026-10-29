
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from src.api.parked_work_listing import background_open_for
from src.core.attention.transcript_facts import read_transcript_facts
from src.core.background_work.open_count import BackgroundCountReader

UUID = "c45140e9-528c-44ba-81ad-f56ce9c2a37e"
CLAUDE_PID = 4558
NOW = datetime(2026, 9, 28, 16, 34, 0, tzinfo=timezone.utc)
PROCESS_START = NOW - timedelta(hours=26)


def _stamp(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (at.microsecond // 1000)


def _base(kind: str, at: datetime, n: int, agent: Optional[str]) -> Dict[str, Any]:
    record = {"parentUuid": "p%d" % n, "isSidechain": agent is not None,
              "type": kind, "uuid": "u%d-%s" % (n, agent or "main"),
              "timestamp": _stamp(at), "userType": "external", "entrypoint": "cli",
              "cwd": "/w", "sessionId": UUID, "version": "2.1.283", "gitBranch": "main"}
    if agent is not None:
        record["agentId"] = agent
    return record


def _shell_launch(task_id: str, at: datetime, n: int, agent: Optional[str] = None,
                  timed_out: bool = False) -> Dict[str, Any]:
    record = _base("user", at, n, agent)
    text = ("Command did not complete within its 120s timeout and was moved to the "
            "background" if timed_out else "Command running in background with ID: "
            + task_id) + ". Output is being written to: /t/tasks/%s.output" % task_id
    record["message"] = {"role": "user", "content": [
        {"tool_use_id": "toolu_%s" % task_id, "type": "tool_result",
         "content": text, "is_error": False}]}
    result = {"stdout": "", "stderr": "", "interrupted": False, "isImage": False,
              "noOutputExpected": False, "backgroundTaskId": task_id}
    if timed_out:
        result["timedOutAfterMs"] = 120000
    record["toolUseResult"] = result
    return record


def _monitor_launch(task_id: str, at: datetime, n: int) -> Dict[str, Any]:
    record = _base("user", at, n, None)
    record["message"] = {"role": "user", "content": [
        {"tool_use_id": "toolu_%s" % task_id, "type": "tool_result",
         "content": "Monitor started", "is_error": False}]}
    record["toolUseResult"] = {"taskId": task_id, "timeoutMs": 1800000, "persistent": False}
    return record


def _notice(task_id: str, at: datetime, n: int) -> Dict[str, Any]:
    record = {"type": "queue-operation", "operation": "enqueue", "timestamp": _stamp(at),
              "sessionId": UUID,
              "content": "<task-notification>\n<task-id>%s</task-id>\n<status>completed"
                         "</status>\n</task-notification>" % task_id}
    return record


def _text(at: datetime, n: int, size: int) -> Dict[str, Any]:
    record = _base("assistant", at, n, None)
    record["message"] = {"role": "assistant", "type": "message", "model": "m",
                         "content": [{"type": "text", "text": "x" * size}]}
    return record


def _write(path: Path, records: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def _conversation(root: Path) -> Path:
    parent = root / ("%s.jsonl" % UUID)
    early = NOW - timedelta(hours=2)
    records = [
        _shell_launch("bug3jtaip", early, 1),
        _monitor_launch("bj2jlobx5", NOW - timedelta(hours=3), 2),
        _monitor_launch("bmlive001", NOW - timedelta(minutes=5), 3),
    ]
    records += [_text(early + timedelta(seconds=i), 10 + i, 20000) for i in range(21)]
    records += [_notice("bi96omv3n", NOW - timedelta(minutes=40), 90),
                _notice("21ab01df72ae2f11c", NOW - timedelta(minutes=58), 91)]
    _write(parent, records)
    agents = root / UUID / "subagents"
    _write(agents / "agent-21ab01df72ae2f11c.jsonl", [
        _shell_launch("bn4jqda82", NOW - timedelta(minutes=67), 1, "21ab01df72ae2f11c",
                      timed_out=True)])
    _write(agents / "agent-11949fccaacc73d6e.jsonl", [
        _shell_launch("bi96omv3n", NOW - timedelta(minutes=45), 1, "11949fccaacc73d6e"),
        _shell_launch("bdmulccqj", NOW - timedelta(minutes=4), 2, "11949fccaacc73d6e")])
    return parent


STDOUT = {101: "/t/tasks/bug3jtaip.output", 102: "/t/tasks/bn4jqda82.output",
          103: "/t/tasks/bdmulccqj.output", 104: "/t/tasks/b432iwsbq.output",
          105: None, 106: None}


def _parents(*gone: int) -> Dict[int, int]:
    table = {pid: CLAUDE_PID for pid in (101, 102, 103, 104, 105)}
    table[106] = 102
    table[CLAUDE_PID] = 1
    return {pid: ppid for pid, ppid in table.items() if pid not in gone}


def test_count_matches_claude_shells_for_parent_and_subagent_launches(tmp_path: Path) -> None:
    parent = _conversation(tmp_path)
    assert parent.stat().st_size > 256 * 1024
    assert read_transcript_facts(str(parent)).open_background_tasks == 0

    reader = BackgroundCountReader(stdout_of=STDOUT.get, clock=lambda: 0.0)
    count = reader.read(parent, claude_pid=CLAUDE_PID, process_parents=_parents(),
                        process_started_at=PROCESS_START, now=NOW)
    assert count == 4

    after = reader.read(parent, claude_pid=CLAUDE_PID, process_parents=_parents(102, 106),
                        process_started_at=PROCESS_START, now=NOW)
    assert after == 3

    assert reader.read(parent, claude_pid=None, process_parents=_parents(),
                       process_started_at=PROCESS_START, now=NOW) is None

    evidence = SimpleNamespace(background_open=count, parked_work=None,
                               transcript=SimpleNamespace(verdict="found",
                                                          open_background_tasks=0))
    observation = SimpleNamespace(stale=False, evidence=evidence)
    watcher = SimpleNamespace(observation_for=lambda session_id, now: observation)
    info = SimpleNamespace(agent_family="claude", session=SimpleNamespace(id="row-1"))
    assert background_open_for(watcher, info, NOW) == 4

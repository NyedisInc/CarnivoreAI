
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from tests.python.reader_state import fixture_tree

UUID = "cb159b70-cf8a-4b07-8d60-da84888ac3ce"
N_AGENTS = 300
AT = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)

SPAWNER = 0
GROWN = (1, 2)
TRUNCATED = 3
SAME_SIZE = 4


def agent_id(i: int) -> str:
    return "a%016x" % i


def parent_path(root: Path, name: str) -> Path:
    return fixture_tree.project_dir(root) / f"{name}.jsonl"


def agent_path(root: Path, i: int) -> Path:
    return fixture_tree.project_dir(root) / "p0" / "subagents" / f"agent-{agent_id(i)}.jsonl"


def _ts(n: int) -> str:
    return (AT + timedelta(seconds=n)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _line(record: Dict[str, Any]) -> str:
    return json.dumps(record, separators=(",", ":")) + "\n"


def _result(tool_id: str, text: str) -> Dict[str, Any]:
    return {"role": "user", "content": [{"tool_use_id": tool_id, "type": "tool_result",
                                         "is_error": False, "content": text}]}


def _shell(task: str, agent: Optional[str], n: int) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "parentUuid": "p%d" % n, "isSidechain": agent is not None, "type": "user",
        "uuid": "u%d-%s" % (n, task), "sessionId": UUID, "timestamp": _ts(n),
        "message": _result("toolu_%s" % task, "Command running in background with ID: %s. "
                           "Output is being written to: /t/tasks/%s.output" % (task, task)),
        "toolUseResult": {"stdout": "", "stderr": "", "interrupted": False, "isImage": False,
                          "noOutputExpected": False, "backgroundTaskId": task}}
    if agent is not None:
        record["agentId"] = agent
    return record


def _monitor(task: str, agent: str, n: int, persistent: bool) -> Dict[str, Any]:
    return {"isSidechain": True, "agentId": agent, "type": "user", "timestamp": _ts(n),
            "message": _result("toolu_%s" % task, "Monitor started (task %s)" % task),
            "toolUseResult": {"taskId": task, "timeoutMs": 1800000, "persistent": persistent}}


def _stop(task: str, agent: str, n: int) -> Dict[str, Any]:
    return {"isSidechain": True, "agentId": agent, "type": "user", "timestamp": _ts(n),
            "message": _result("toolu_stop_%s" % task, "stopped"),
            "toolUseResult": {"task_id": task, "task_type": "local_bash"}}


def _bare(tool_id: str, agent: str, n: int) -> Dict[str, Any]:
    return {"isSidechain": True, "agentId": agent, "type": "user", "timestamp": _ts(n),
            "message": _result(tool_id, "nested agent finished")}


def _notice(agent: str, status: str) -> str:
    return ("<task-notification>\n<task-id>%s</task-id>\n<tool-use-id>toolu_x</tool-use-id>\n"
            "<status>%s</status>\n<summary>redacted</summary>\n</task-notification>" % (agent, status))


def _enqueue(agent: str, status: str, n: int) -> Dict[str, Any]:
    return {"type": "queue-operation", "operation": "enqueue", "timestamp": _ts(n),
            "sessionId": UUID, "content": _notice(agent, status)}


def _queued(agent: str, status: str, n: int) -> Dict[str, Any]:
    return {"type": "attachment", "timestamp": _ts(n), "sessionId": UUID,
            "attachment": {"type": "queued_command", "prompt": _notice(agent, status)}}


def _delivered(agent: str, status: str, n: int) -> Dict[str, Any]:
    return {"type": "user", "timestamp": _ts(n), "sessionId": UUID,
            "origin": {"kind": "task-notification"},
            "message": {"role": "user", "content": _notice(agent, status)}}


def _prompt(n: int) -> Dict[str, Any]:
    return {"isSidechain": False, "type": "user", "timestamp": _ts(n), "sessionId": UUID,
            "origin": {"kind": "human"}, "promptSource": "typed",
            "message": {"role": "user", "content": "go %d" % n}}


def _sync_end(agent: str, n: int) -> Dict[str, Any]:
    return {"isSidechain": False, "type": "user", "timestamp": _ts(n), "sessionId": UUID,
            "message": _result("toolu_sync", "done"),
            "toolUseResult": {"agentId": agent, "status": "completed"}}


def _agent_text(i: int) -> str:
    a, task = agent_id(i), "b%08d" % i
    records: List[Dict[str, Any]] = [_shell(task, a, 1)]
    if i % 10 == 0:
        records.append(_monitor("m%08d" % i, a, 2, persistent=i % 20 == 0))
    if i % 25 == 0:
        records.append(_stop(task, a, 3))
    if i % 7 == 0:
        records.append(_enqueue(task, "completed", 3))
    if i == SPAWNER:
        records += [_bare("toolu_nested1", a, 4), _bare("toolu_nested2", a, 5)]
    return "".join(_line(r) for r in records)


def _p0_half() -> str:
    return _line(_enqueue(agent_id(5), "completed", 20))


def build_phase1(root: Path) -> None:
    fixture_tree.project_dir(root).mkdir(parents=True, exist_ok=True)
    agent_path(root, 0).parent.mkdir(parents=True, exist_ok=True)
    p0 = [_prompt(0), _shell("bparent0", None, 6), _sync_end(agent_id(2), 7),
          _enqueue(agent_id(1), "completed", 8), _queued(agent_id(2), "stopped", 9),
          _delivered(agent_id(3), "completed", 10), _prompt(11)]
    parent_path(root, "p0").write_text("".join(_line(r) for r in p0) + _p0_half()[:-9])
    p1 = [_prompt(1), _enqueue(agent_id(9), "completed", 2), _delivered(agent_id(8), "failed", 3)]
    parent_path(root, "p1").write_text("".join(_line(r) for r in p1))
    for i in range(N_AGENTS):
        agent_path(root, i).write_text(_agent_text(i))


def apply_phase2(root: Path) -> None:
    with open(parent_path(root, "p0"), "ab") as handle:
        handle.write(_p0_half()[-9:].encode())
        handle.write("".join(_line(r) for r in (_prompt(30), _enqueue(agent_id(6), "failed", 31))).encode())
    for i in GROWN:
        with open(agent_path(root, i), "ab") as handle:
            handle.write("".join(_line(r) for r in (
                _shell("bnew%05d" % i, agent_id(i), 40), _stop("b%08d" % i, agent_id(i), 41))).encode())
    with open(agent_path(root, SPAWNER), "ab") as handle:
        handle.write(_line(_bare("toolu_nested3", agent_id(SPAWNER), 42)).encode())
    agent_path(root, TRUNCATED).write_text(_line(_monitor("mshort", agent_id(TRUNCATED), 9, True)))
    old = _agent_text(SAME_SIZE).encode()
    new = old.replace(b'"parentUuid":"p1"', b'"parentUuid":"p2"').replace(b"b%08d" % SAME_SIZE, b"c%08d" % SAME_SIZE)
    assert len(new) == len(old) and new[:256] != old[:256]
    agent_path(root, SAME_SIZE).write_bytes(new)


def changed_agent_stems() -> List[str]:
    return sorted("agent-" + agent_id(i) for i in (TRUNCATED, SAME_SIZE))

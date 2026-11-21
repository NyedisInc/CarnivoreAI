
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from src.core.attention.transcript_facts import TranscriptFacts, read_transcript_facts
from src.core.mcp_health.history import reset_history
from src.core.timeline.context import ExtractContext
from src.core.timeline.extract import extract_line
from src.core.timeline.facts_adapter import facts_from_state
from src.core.timeline.fold import ConvState, fold_record

CONV = "c0000002-0000-4000-9000-000000000000"
TAIL, WIDE = 4096, 1 << 20
NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
NO_SKIP: FrozenSet[str] = frozenset()
Line = Tuple[Dict[str, Any], bytes, int]


def at(second: int) -> str:
    return f"2026-11-01T{10 + second // 3600:02d}:{second % 3600 // 60:02d}:{second % 60:02d}.000Z"


def user(second: int, content: Any, **extra: Any) -> Dict[str, Any]:
    return {"type": "user", "timestamp": at(second), "message": {"role": "user", "content": content}, **extra}


def assistant(second: int, blocks: List[Dict[str, Any]], msg: str = "m", stop: str = "tool_use", **extra: Any) -> Dict[str, Any]:
    return {"type": "assistant", "timestamp": at(second), "message": {
        "id": msg, "model": "m", "stop_reason": stop, "content": blocks}, **extra}


def call(call_id: str, name: str) -> Dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": {"command": "ls"}}


def result(second: int, call_id: str, **tool_result: Any) -> Dict[str, Any]:
    return user(second, [{"type": "tool_result", "tool_use_id": call_id, "content": "ok"}], toolUseResult=tool_result)


def agent_launch(second: int, call_id: str, agent: str) -> Dict[str, Any]:
    return result(second, call_id, isAsync=True, agentId=agent, status="async_launched")


def shell_launch(second: int, call_id: str, task: str) -> Dict[str, Any]:
    return result(second, call_id, backgroundTaskId=task)


def workflow_launch(second: int, call_id: str, task: str) -> Dict[str, Any]:
    return result(second, call_id, status="async_launched", taskType="local_workflow", taskId=task)


def monitor_launch(second: int, call_id: str, task: str) -> Dict[str, Any]:
    return result(second, call_id, persistent=True, taskId=task)


def stop_result(second: int, call_id: str, task: str) -> Dict[str, Any]:
    return result(second, call_id, task_id=task, task_type="local_bash")


def notice_text(task: str, call_id: str) -> str:
    return (f"<task-notification><task-id>{task}</task-id><tool-use-id>{call_id}</tool-use-id>"
            "<status>completed</status></task-notification>")


def notice(second: int, task: str, call_id: str) -> Dict[str, Any]:
    return user(second, notice_text(task, call_id), origin={"kind": "task-notification"})


def enqueue(second: int, task: str, call_id: str) -> Dict[str, Any]:
    return {"type": "queue-operation", "operation": "enqueue", "timestamp": at(second), "content": notice_text(task, call_id)}


def turn_end(second: int, pending: int = 0, **extra: Any) -> Dict[str, Any]:
    record: Dict[str, Any] = {"type": "system", "subtype": "turn_duration", "timestamp": at(second),
                              "durationMs": 1000, "version": "2.1.266", **extra}
    if pending:
        record["pendingBackgroundAgentCount"] = pending
    return record


def esc(second: int, tool: bool = False) -> Dict[str, Any]:
    text = "[Request interrupted by user for tool use]" if tool else "[Request interrupted by user]"
    return user(second, [{"type": "text", "text": text}])


def pad(second: int, index: int) -> Dict[str, Any]:
    return assistant(second, [{"type": "text", "text": "w" * 400}], msg=f"pad{index}", stop="end_turn")


def quiet_pad(second: int) -> Dict[str, Any]:
    return {"type": "attachment", "timestamp": at(second), "attachment": {"type": "diagnostics", "blob": "w" * 400}}


def mcp_removed(second: int) -> Dict[str, Any]:
    return {"type": "attachment", "timestamp": at(second), "attachment": {
        "type": "deferred_tools_delta", "removedNames": ["mcp__demo__tool"], "addedNames": []}}


def write(path: Path, records: List[Dict[str, Any]]) -> List[Line]:
    lines, offset, out = [], 0, []
    for record in records:
        raw = json.dumps(record, separators=(",", ":")).encode()
        offset += len(raw) + 1
        lines.append(raw)
        out.append((record, raw, offset))
    path.write_bytes(b"\n".join(lines) + b"\n")
    return out


def fold_lines(lines: List[Line], *, from_line: int = 0, retain_bytes: Optional[int] = None) -> ConvState:
    start = lines[from_line - 1][2] if from_line else 0
    state, ctx = ConvState(conv=CONV, coverage_start=start, retain_bytes=retain_bytes), ExtractContext(conv=CONV)
    for record, raw, end in lines[from_line:]:
        fold_record(state, record, extract_line(ctx, raw, end), end)
    return state


def differences(got: TranscriptFacts, want: TranscriptFacts, skip: FrozenSet[str]) -> List[str]:
    return [f"{f.name}: {getattr(got, f.name)!r} != {getattr(want, f.name)!r}" for f in dataclasses.fields(TranscriptFacts)
            if f.name not in skip and getattr(got, f.name) != getattr(want, f.name)]


@dataclass
class Case:

    path: Path
    lines: List[Line]
    state: ConvState

    @property
    def size(self) -> int:
        return self.path.stat().st_size

    def legacy(self, tail: int = TAIL, wide: int = WIDE) -> TranscriptFacts:
        reset_history()
        return read_transcript_facts(str(self.path), tail_bytes=tail, wide_tail_bytes=wide, now=NOW)

    def fold(self, tail: int = TAIL, wide: int = WIDE, state: Optional[ConvState] = None) -> TranscriptFacts:
        return facts_from_state(state or self.state, now=NOW, size=self.size, tail_bytes=tail, wide_tail_bytes=wide,
                                fresh_history=True)


def build(tmp_path: Path, name: str, records: List[Dict[str, Any]]) -> Case:
    path = tmp_path / f"{name}.jsonl"
    lines = write(path, records)
    return Case(path, lines, fold_lines(lines))

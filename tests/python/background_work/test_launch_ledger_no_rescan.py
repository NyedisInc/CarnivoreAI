
from __future__ import annotations

import builtins
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.subagents import parent_index, parked_launches
from src.core.subagents.parked_launches import conversation_launches

UUID = "cb159b70-cf8a-4b07-8d60-da84888ac3ce"
FILES = 300
AT = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)


def _launch(task_id: str, agent: str, n: int) -> Dict[str, Any]:
    return {
        "parentUuid": "p%d" % n, "isSidechain": True, "type": "user",
        "uuid": "u%d-%s" % (n, agent), "agentId": agent, "sessionId": UUID,
        "timestamp": (AT + timedelta(seconds=n)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "message": {"role": "user", "content": [{
            "tool_use_id": "toolu_%s" % task_id, "type": "tool_result", "is_error": False,
            "content": "Command running in background with ID: %s. Output is being "
                       "written to: /t/tasks/%s.output" % (task_id, task_id)}]},
        "toolUseResult": {"stdout": "", "stderr": "", "interrupted": False,
                          "isImage": False, "noOutputExpected": False,
                          "backgroundTaskId": task_id},
    }


def _line(record: Dict[str, Any]) -> str:
    return json.dumps(record) + "\n"


def _task_ids(found: List[Any]) -> List[str]:
    return sorted(launch.task_id for launch, _retired in found)


def test_unchanged_files_are_not_reopened_and_an_append_is_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / ("%s.jsonl" % UUID)
    parent.write_text(_line({"type": "user", "sessionId": UUID,
                             "timestamp": "2026-09-30T11:00:00.000Z",
                             "message": {"role": "user", "content": "go"}}))
    agents = tmp_path / UUID / "subagents"
    agents.mkdir(parents=True)
    paths = []
    for i in range(FILES):
        agent = "a%016x" % i
        path = agents / ("agent-%s.jsonl" % agent)
        path.write_text(_line(_launch("b%08d" % i, agent, 1)))
        paths.append(path)

    opened: List[str] = []
    real_open = builtins.open

    def counting_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if "agent-" in str(file):
            opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(parked_launches, "open", counting_open, raising=False)
    monkeypatch.setattr(parent_index, "open", counting_open, raising=False)

    first = conversation_launches(parent)
    assert first is not None and len(first) == FILES
    assert len(opened) >= FILES

    opened.clear()
    second = conversation_launches(parent)
    assert _task_ids(second) == _task_ids(first)
    assert opened == []

    target = paths[7]
    with real_open(target, "a") as handle:
        handle.write(_line(_launch("bappended", "a%016x" % 7, 2)))
    opened.clear()
    third = conversation_launches(parent)
    assert _task_ids(third) == sorted(_task_ids(first) + ["bappended"])
    assert set(opened) == {str(target)}

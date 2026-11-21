
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Set

import pytest

from src.core.attention import fs_event_index
from src.core.subagents import launch_memo, parked_launches
from src.core.subagents.parked_launches import conversation_launches

UUID = "5f0c1a2b-3c4d-4e5f-8a9b-0c1d2e3f4a5b"
FILES = 40
AT = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)


class _Index:

    def __init__(self, roots: tuple) -> None:
        self.watching = True
        self._watched = roots
        self.callbacks: List[Callable[[Set[str]], None]] = []

    def subscribe(self, callback: Callable[[Set[str]], None]) -> Callable[[], None]:
        self.callbacks.append(callback)
        return lambda: None

    def fire(self, paths: Set[str]) -> None:
        for callback in self.callbacks:
            callback(paths)


def _launch(task_id: str, agent: str) -> Dict[str, Any]:
    return {
        "parentUuid": "p", "isSidechain": True, "type": "user", "uuid": "u-%s" % task_id, "agentId": agent,
        "sessionId": UUID, "timestamp": (AT + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "message": {"role": "user", "content": [{
            "tool_use_id": "toolu_%s" % task_id, "type": "tool_result", "is_error": False,
            "content": "Command running in background with ID: %s. Output is being written to: "
                       "/t/tasks/%s.output" % (task_id, task_id)}]},
        "toolUseResult": {"stdout": "", "stderr": "", "interrupted": False, "isImage": False,
                          "noOutputExpected": False, "backgroundTaskId": task_id},
    }


def _line(record: Dict[str, Any]) -> str:
    return json.dumps(record) + "\n"


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "projects"
    parent = root / ("%s.jsonl" % UUID)
    agents = root / UUID / "subagents"
    agents.mkdir(parents=True)
    parent.write_text(_line({"type": "user", "sessionId": UUID, "timestamp": "2026-11-15T11:00:00.000Z",
                             "message": {"role": "user", "content": "go"}}))
    for i in range(FILES):
        agent = "a%016x" % i
        (agents / ("agent-%s.jsonl" % agent)).write_text(_line(_launch("b%08d" % i, agent)))
    index = _Index((str(root),))
    monkeypatch.setattr(fs_event_index, "_index", index)
    monkeypatch.setattr(launch_memo, "_subscribed_to", None)
    launch_memo.forget_all()
    stats: List[str] = []
    real_stat = os.stat

    def counting_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        if "agent-" in str(path):
            stats.append(str(path))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(parked_launches.os, "stat", counting_stat)
    yield parent, agents, index, stats
    launch_memo.forget_all()


def _ids(found: List[Any]) -> List[str]:
    return sorted(launch.task_id for launch, _retired in found)


def test_an_unchanged_conversation_costs_no_sub_agent_stat(tree) -> None:
    parent, _agents, _index, stats = tree
    first = conversation_launches(parent)
    assert len(_ids(first)) == FILES
    stats.clear()
    assert _ids(conversation_launches(parent)) == _ids(first)
    assert stats == []


def test_an_event_on_a_sub_agent_file_brings_its_new_launch(tree) -> None:
    parent, agents, index, _stats = tree
    conversation_launches(parent)
    path = agents / ("agent-%s.jsonl" % ("a%016x" % 0))
    with open(path, "a") as handle:
        handle.write(_line(_launch("znew0001", "a%016x" % 0)))
    assert "znew0001" not in _ids(conversation_launches(parent))
    index.fire({os.path.realpath(str(path))})
    assert "znew0001" in _ids(conversation_launches(parent))


def test_a_resync_or_a_dead_stream_reads_again(tree) -> None:
    parent, _agents, index, stats = tree
    conversation_launches(parent)
    stats.clear()
    index.fire({fs_event_index.RESYNC})
    conversation_launches(parent)
    assert len(stats) >= FILES
    index.watching = False
    stats.clear()
    conversation_launches(parent)
    assert len(stats) >= FILES


def test_an_entry_expires_after_the_rescan_interval(tree, monkeypatch: pytest.MonkeyPatch) -> None:
    parent, _agents, _index, stats = tree
    clock = [1000.0]
    monkeypatch.setattr(launch_memo.time, "monotonic", lambda: clock[0])
    conversation_launches(parent)
    stats.clear()
    clock[0] += launch_memo.MAX_AGE_SECONDS + 1
    conversation_launches(parent)
    assert len(stats) >= FILES


def test_an_answer_read_across_an_event_is_not_kept(tree, monkeypatch: pytest.MonkeyPatch) -> None:
    parent, agents, index, stats = tree
    real = parked_launches._read_conversation

    def read_then_event(path: Path) -> Any:
        answer = real(path)
        index.fire({str(agents / "agent-x.jsonl")})
        return answer

    monkeypatch.setattr(parked_launches, "_read_conversation", read_then_event)
    conversation_launches(parent)
    monkeypatch.setattr(parked_launches, "_read_conversation", real)
    stats.clear()
    conversation_launches(parent)
    assert len(stats) >= FILES


def test_conversation_uuid_reads_parent_and_sub_agent_paths() -> None:
    assert launch_memo.conversation_uuid("/a/projects.nosync/d/%s.jsonl" % UUID) == UUID
    assert launch_memo.conversation_uuid("/a/d/%s/subagents/agent-x.jsonl" % UUID.upper()) == UUID
    assert launch_memo.conversation_uuid("/a/d/%s/subagents" % UUID) == UUID
    assert launch_memo.conversation_uuid("/a/d/notes.txt") is None


def test_an_event_on_the_parent_transcript_reads_again(tree) -> None:
    parent, _agents, index, stats = tree
    conversation_launches(parent)
    stats.clear()
    index.fire({os.path.realpath(str(parent))})
    conversation_launches(parent)
    assert len(stats) >= FILES


def test_a_file_still_warming_is_not_remembered(tree, monkeypatch: pytest.MonkeyPatch) -> None:
    parent, agents, _index, stats = tree
    big = agents / ("agent-%s.jsonl" % ("b%016x" % 1))
    big.write_text("".join(_line(_launch("w%07d" % n, "b%016x" % 1)) for n in range(50)))
    monkeypatch.setattr(parked_launches, "PARENT_SLICE_BYTES", 2048)
    conversation_launches(parent)
    stats.clear()
    conversation_launches(parent)
    assert str(big) in stats

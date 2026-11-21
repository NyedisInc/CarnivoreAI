
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, List, Set

import pytest

from src.core.attention import fs_event_index
from src.core.subagents import launch_memo, scan_inputs
from src.core.subagents.scan_inputs import agent_files_signature

UUID = "6a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
FILES = 30


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


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "projects"
    agents = root / UUID / "subagents"
    agents.mkdir(parents=True)
    for i in range(FILES):
        (agents / ("agent-a%04d.jsonl" % i)).write_text("{}\n")
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

    monkeypatch.setattr(scan_inputs.os, "stat", counting_stat)
    yield agents, index, stats
    launch_memo.forget_all()


def test_an_unchanged_folder_costs_no_stat_and_compares_equal(tree) -> None:
    agents, _index, stats = tree
    first = agent_files_signature(agents)
    assert isinstance(first, tuple) and len(first) == FILES
    stats.clear()
    second = agent_files_signature(agents)
    assert second == first and isinstance(second, tuple)
    assert stats == []


def test_an_event_in_the_folder_reads_it_again(tree) -> None:
    agents, index, _stats = tree
    first = agent_files_signature(agents)
    added = agents / "agent-znew.jsonl"
    added.write_text("{}\n")
    index.fire({str(added)})
    second = agent_files_signature(agents)
    assert len(second) == FILES + 1 and second != first


def test_a_resync_or_a_dead_stream_reads_again(tree) -> None:
    agents, index, stats = tree
    agent_files_signature(agents)
    index.fire({fs_event_index.RESYNC})
    stats.clear()
    agent_files_signature(agents)
    assert len(stats) == FILES
    index.watching = False
    stats.clear()
    agent_files_signature(agents)
    assert len(stats) == FILES


def test_a_vanished_file_is_never_remembered(tree, monkeypatch: pytest.MonkeyPatch) -> None:
    agents, _index, stats = tree
    real_stat = scan_inputs.os.stat

    def flaky(path: Any, *args: Any, **kwargs: Any) -> Any:
        if str(path).endswith("agent-a0000.jsonl") and not flaky.failed:
            flaky.failed = True
            raise FileNotFoundError(path)
        return real_stat(path, *args, **kwargs)

    flaky.failed = False
    monkeypatch.setattr(scan_inputs.os, "stat", flaky)
    first = agent_files_signature(agents)
    assert first[0][1] is None
    second = agent_files_signature(agents)
    assert second[0][1] is not None


def test_a_missing_folder_is_the_empty_signature(tree) -> None:
    agents, _index, _stats = tree
    assert agent_files_signature(agents.parent.parent / UUID.replace("6a", "7b") / "subagents") == ()


def test_a_closing_span_reads_bytes_the_memory_has_not_seen(tree) -> None:
    from src.core.skill_watch.spans import advance, new_state

    agents, _index, _stats = tree
    main = agents.parent.parent / ("%s.jsonl" % UUID)

    def line(obj: dict) -> str:
        import json
        return json.dumps(obj) + "\n"

    fire = {"type": "assistant", "timestamp": "2026-09-28T10:00:00Z", "cwd": "/work/a", "message": {
        "id": "f1", "content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "review"}}]}}
    main.write_text(line(fire))
    target = agents / "agent-a0001.jsonl"
    state = new_state(0)
    advance(str(main), state)
    curl = {"type": "assistant", "isSidechain": True, "timestamp": "2026-09-28T10:00:05Z", "message": {
        "id": "c1", "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "curl late.test"}}]}}
    with open(target, "a") as handle:
        handle.write(line(curl))
    with open(main, "a") as handle:
        handle.write(line({"type": "user", "timestamp": "2026-09-28T10:00:09Z", "message": {"content": "thanks"}}))
    advance(str(main), state)
    assert state.done and state.subs_final
    assert state.facts.categories.get("network") == 1


def test_expired_entries_are_dropped_once_the_memory_is_large(tree, monkeypatch: pytest.MonkeyPatch) -> None:
    agents, _index, _stats = tree
    monkeypatch.setattr(launch_memo, "PRUNE_ABOVE", 2)
    for n in range(4):
        launch_memo._ENTRIES[("/gone/%d" % n, UUID)] = (-1e9, ())  # noqa: SLF001
    agent_files_signature(agents)
    assert all(not key[0].startswith("/gone/") for key in launch_memo._ENTRIES)  # noqa: SLF001

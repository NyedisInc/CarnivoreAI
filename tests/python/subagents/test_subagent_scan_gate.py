
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_scangate_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_scangate_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.subagents import files, parked_work, reader
from src.core.subagents.scan_inputs import agent_files_signature
from src.core.subagents.tally import SubagentTallyCache
from tests.helpers.subagent_fixture import (
    CONV, _parent, assistant, build_corpus, notification, ts, user,
)

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
NEW_AGENT = "a0000000000000010"


class _Clock:

    def __init__(self) -> None:
        self.at = 1000.0

    def __call__(self) -> float:
        return self.at


@pytest.fixture(autouse=True)
def _fresh():
    files.reset_caches_for_tests()
    yield
    files.reset_caches_for_tests()


@pytest.fixture
def scans(monkeypatch):
    calls = []
    real = reader._scan
    monkeypatch.setattr(reader, "_scan", lambda directory: calls.append(directory) or real(directory))
    return calls


@pytest.fixture
def world(tmp_path):
    root = tmp_path / "projects"
    parent = build_corpus(root)
    clock = _Clock()
    return SimpleNamespace(root=root, parent=parent, clock=clock,
                           cache=SubagentTallyCache(projects_dir=root, clock=clock))


def _cycle(world):
    world.clock.at += 2
    return world.cache.tally("claude", CONV, None, None, NOW)


def _append_parent(parent: Path, record: dict) -> None:
    with parent.open("a") as handle:
        handle.write(json.dumps(record) + "\n")


def _add_running_agent(parent: Path) -> None:
    sub = parent.with_suffix("") / "subagents"
    (sub / f"agent-{NEW_AGENT}.meta.json").write_text(
        json.dumps({"agentType": "worker", "description": "new", "toolUseId": "toolu_N"}))
    with open(sub / f"agent-{NEW_AGENT}.jsonl", "w") as handle:
        for line in (user(NEW_AGENT, ts(11, 59)), assistant(NEW_AGENT, ts(11, 59, 30))):
            handle.write(json.dumps(line) + "\n")


def test_unchanged_session_is_not_rescanned_even_while_the_parent_grows(world, scans):
    first = _cycle(world)
    assert len(scans) == 1
    for _ in range(5):
        _append_parent(world.parent, _parent("assistant", ts(11, 59), requestId="r"))
        assert _cycle(world) == first
    assert len(scans) == 1, "five parent-only growths must not re-run the scan"


def test_a_new_subagent_flips_the_count_on_the_next_cycle(world, scans):
    before = _cycle(world)
    _append_parent(world.parent, _parent("assistant", ts(11, 59), requestId="r"))
    _add_running_agent(world.parent)
    after = _cycle(world)
    assert after.total == before.total + 1
    assert after.running == before.running + 1
    assert len(scans) == 2


def test_a_finished_subagent_clears_running_on_the_next_cycle(world, scans):
    _add_running_agent(world.parent)
    running = _cycle(world)
    assert running.running >= 1
    _append_parent(world.parent, _parent(
        "user", ts(11, 59, 50), promptId="p", origin={"kind": "task-notification"},
        message={"role": "user", "content": notification([NEW_AGENT], "completed")}))
    after = _cycle(world)
    assert after.running == running.running - 1
    assert after.total == running.total


def test_an_appended_agent_file_with_no_parent_or_directory_change_is_seen(world, scans):
    _add_running_agent(world.parent)
    _cycle(world)
    sub = world.parent.with_suffix("") / "subagents"
    before = agent_files_signature(sub)
    with open(sub / f"agent-{NEW_AGENT}.jsonl", "a") as handle:
        handle.write(json.dumps(assistant(NEW_AGENT, ts(11, 59, 50))) + "\n")
    _append_parent(world.parent, _parent("assistant", ts(11, 59), requestId="r"))
    assert agent_files_signature(sub) != before
    _cycle(world)
    assert len(scans) == 2


def test_the_clock_rung_still_refreshes_an_unchanged_session(world, scans):
    _cycle(world)
    world.clock.at += 31
    _cycle(world)
    assert len(scans) == 2


def test_signature_of_a_missing_folder_is_a_measured_empty_and_an_unreadable_one_is_none(tmp_path):
    assert agent_files_signature(tmp_path / "nope") == ()
    (tmp_path / "plain").write_text("a file, not a folder")
    assert agent_files_signature(tmp_path / "plain") is None


def test_parked_launches_are_not_rescanned_while_only_the_parent_grows(world, monkeypatch):
    calls = []
    real = parked_work.find_open_launches
    monkeypatch.setattr(parked_work, "find_open_launches",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    clock = _Clock()
    reader_ = parked_work.ParkedWorkReader(clock=clock)
    facts = SimpleNamespace(newest_user_prompt_at=None)
    started = datetime(2026, 9, 26, 9, 0, tzinfo=timezone.utc)

    def cycle():
        clock.at += 2
        return reader_._launches(world.parent, facts, started, NOW)

    first = cycle()
    for _ in range(4):
        _append_parent(world.parent, _parent("assistant", ts(11, 59), requestId="r"))
        assert cycle() == first
    assert len(calls) == 1
    _add_running_agent(world.parent)
    cycle()
    assert len(calls) == 2

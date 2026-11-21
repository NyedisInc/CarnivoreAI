
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_3036_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_3036_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.attention import fs_event_index
from src.core.skill_fires.store import SkillFireStore
from src.core.skill_fires.tally import STATE_MEASURED, SkillTallyCache
from src.core.subagents import files, reader
from src.core.subagents.scan_inputs import read_agent_files_signature
from src.core.subagents.tally import SubagentTallyCache
from tests.helpers.subagent_fixture import A, B, CONV, E, F, _parent, assistant, build_corpus, ts, user

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
UUID_A = "019a1b2c-3d4e-5f60-7182-93a4b5c6d7e8"
UUID_B = "019a1b2c-3d4e-5f60-7182-93a4b5c6d7e9"


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
def world(tmp_path):
    root = tmp_path / "projects"
    parent = build_corpus(root)
    clock = _Clock()
    cache = SubagentTallyCache(projects_dir=root, clock=clock)
    return root, parent, clock, cache, parent.with_suffix("") / "subagents"


def _agent_stats(monkeypatch) -> List[tuple]:
    seen: List[tuple] = []
    real = os.stat

    def counting(path: Any, *args: Any, **kwargs: Any) -> Any:
        if "agent-" in str(path):
            seen.append((str(path), os.path.basename(sys._getframe(1).f_code.co_filename)))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", counting)
    return seen


def _opens(monkeypatch) -> List[str]:
    seen: List[str] = []
    real = open

    def counting(path: Any, *args: Any, **kwargs: Any) -> Any:
        if "agent-" in str(path):
            seen.append(str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(files, "open", counting, raising=False)
    return seen


def _oracle(parent: Path):
    files.reset_caches_for_tests()
    return reader.read_subagents(parent, conversation_uuid=CONV, now=NOW)


def _cycle(clock: _Clock, cache: SubagentTallyCache, parent: Path):
    with parent.open("a") as handle:
        handle.write(json.dumps(_parent("assistant", ts(11, 59), requestId="r")) + "\n")
    clock.at += 2
    return cache.tally("claude", CONV, None, None, NOW)


def _same_as_oracle(tally, parent: Path) -> None:
    counts = _oracle(parent).counts
    assert (tally.running, tally.total, tally.unknown) == (counts.running, counts.total, counts.unknown)


def test_a_changed_conversation_stats_each_agent_file_once_per_cycle(world, monkeypatch):
    _root, parent, clock, cache, sub = world
    _cycle(clock, cache, parent)
    with (sub / f"agent-{B}.jsonl").open("a") as handle:
        handle.write(json.dumps(assistant(B, ts(11, 59, 30))) + "\n")
    stats = _agent_stats(monkeypatch)
    after = _cycle(clock, cache, parent)
    assert stats, "the changed conversation must be re-read"
    fingerprint = [path for path, caller in stats if caller == "scan_inputs.py"]
    assert len(fingerprint) == len(set(fingerprint)), "the fingerprint stats each file once"
    again = [(path, caller) for path, caller in stats if caller in ("reader.py", "files.py")]
    assert again == [], again
    _same_as_oracle(after, parent)


def test_an_unchanged_file_is_not_reopened_across_cycles(world, monkeypatch):
    _root, parent, clock, cache, sub = world
    _cycle(clock, cache, parent)
    opened = _opens(monkeypatch)
    (sub / f"agent-{B}.meta.json").touch()
    with (sub / f"agent-{F}.jsonl").open("a") as handle:
        handle.write(json.dumps(assistant(F, ts(11, 59, 45))) + "\n")
    _cycle(clock, cache, parent)
    assert [p for p in opened if p.endswith(f"agent-{F}.jsonl")], "the appended file is read"
    assert not [p for p in opened if p.endswith(f"agent-{A}.jsonl")], opened


def test_cached_and_uncached_answers_agree_through_every_kind_of_change(world):
    _root, parent, clock, cache, sub = world
    steps = []
    steps.append(lambda: None)
    steps.append(lambda: (sub / f"agent-{B}.jsonl").open("a").write(
        json.dumps(assistant(B, ts(11, 59, 40))) + "\n"))

    def replace_by_rename() -> None:
        fresh = sub / f"agent-{A}.jsonl.tmp"
        fresh.write_text(json.dumps(user(A, ts(11, 57))) + "\n"
                         + json.dumps(assistant(A, ts(11, 58))) + "\n")
        os.replace(fresh, sub / f"agent-{A}.jsonl")

    steps.append(replace_by_rename)
    steps.append(lambda: (sub / f"agent-{E}.jsonl").unlink())

    def create_new() -> None:
        (sub / "agent-a000000000000099.meta.json").write_text(json.dumps({"agentType": "worker", "toolUseId": "toolu_N"}))
        (sub / "agent-a000000000000099.jsonl").write_text(
            json.dumps(user("a000000000000099", ts(11, 59))) + "\n"
            + json.dumps(assistant("a000000000000099", ts(11, 59, 30))) + "\n")

    steps.append(create_new)
    for step in steps:
        step()
        tally = _cycle(clock, cache, parent)
        _same_as_oracle(tally, parent)
    signature = read_agent_files_signature(sub)
    with_files = reader.read_subagents(parent, conversation_uuid=CONV, now=NOW, files=signature)
    assert with_files == _oracle(parent)
    (sub / f"agent-{F}.jsonl").unlink()
    stale = reader.read_subagents(parent, conversation_uuid=CONV, now=NOW, files=signature)
    assert stale == _oracle(parent)
    import shutil
    shutil.rmtree(sub.parent)
    gone = reader.read_subagents(parent, conversation_uuid=CONV, now=NOW, files=read_agent_files_signature(sub))
    assert gone == _oracle(parent) and gone.counts.total == 0


def _live_memo(monkeypatch) -> dict:
    kept: dict = {}

    def remembered(parent: str, compute: Any) -> Any:
        if parent in kept:
            return kept[parent]
        answer, complete = compute()
        if complete and answer is not None:
            kept[parent] = answer
        return answer

    monkeypatch.setattr("src.core.subagents.launch_memo.remembered", remembered)
    return kept


def test_a_remembered_signature_never_makes_the_derivation_keep_a_stale_answer(world, monkeypatch):
    _root, parent, clock, cache, sub = world
    kept = _live_memo(monkeypatch)
    cache.tally("claude", CONV, None, None, NOW)
    assert kept, "the memo is live for this test"
    with (sub / f"agent-{E}.jsonl").open("a") as handle:
        handle.write(json.dumps(assistant(E, ts(11, 59, 50))) + "\n")
    clock.at += 31
    _same_as_oracle(cache.tally("claude", CONV, None, None, NOW), parent)
    kept.clear()
    for step in (2, 10, 18):
        clock.at += step
        _same_as_oracle(cache.tally("claude", CONV, None, None, NOW), parent)


def test_a_fresh_signature_is_still_shared_and_a_remembered_one_costs_one_stat_per_file(world, monkeypatch):
    _root, parent, clock, cache, sub = world
    kept = _live_memo(monkeypatch)
    _cycle(clock, cache, parent)
    kept.clear()
    with (sub / f"agent-{B}.jsonl").open("a") as handle:
        handle.write(json.dumps(assistant(B, ts(11, 59, 31))) + "\n")
    stats = _agent_stats(monkeypatch)
    _cycle(clock, cache, parent)
    assert [c for _p, c in stats if c in ("reader.py", "files.py")] == []
    names = [path for path, caller in stats if caller == "scan_inputs.py"]
    assert names, "the signature was read now"
    assert len(names) == len(set(names)), "one stat per file when the signature was read now"


def test_the_mtime_taken_from_a_signature_equals_the_one_stat_reports(tmp_path):
    path = tmp_path / "f"
    path.write_text("x")
    for ns in (1_700_000_000_123_456_789, 1_700_000_000_000_000_001, 1_500_000_000_999_999_999):
        os.utime(path, ns=(ns, ns))
        stat = os.stat(path)
        assert files.mtime_seconds(stat.st_mtime_ns) == stat.st_mtime



def _fire_line(skill: str, at: str) -> str:
    return json.dumps({"type": "assistant", "timestamp": at, "message": {"content": [
        {"type": "tool_use", "name": "Skill", "input": {"skill": skill}}]}}, separators=(",", ":")) + "\n"


def test_an_idle_skill_tally_opens_one_store_session_and_answers_like_the_store(tmp_path, monkeypatch):
    db = tmp_path / "skill_fires.db"
    store = SkillFireStore(db)
    transcript = tmp_path / "projects" / "-p" / f"{UUID_A}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(_fire_line("alpha", "2026-11-18T10:00:00Z"))
    cache = SkillTallyCache(store=store, home=tmp_path)
    first = cache.tally("claude", transcript)
    assert (first.state, first.fired, first.last_skill) == (STATE_MEASURED, 1, "alpha")
    seen: List[str] = []
    real = os.stat

    def counting(path: Any, *args: Any, **kwargs: Any) -> Any:
        if str(path) == str(db):
            seen.append(str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", counting)
    assert cache.tally("claude", transcript) == first
    assert len(seen) == 1, seen
    monkeypatch.setattr(os, "stat", real)
    with transcript.open("a") as handle:
        handle.write(_fire_line("beta", "2026-11-18T10:01:00Z"))
    second = cache.tally("claude", transcript)
    latest = store.recent(str(transcript.resolve()), limit=1)
    assert (second.fired, second.last_skill, second.last_at) == (2, "beta", latest[0].fired_at)
    replacement = transcript.with_suffix(".new")
    replacement.write_text(_fire_line("gamma", "2026-11-18T10:02:00Z"))
    os.replace(replacement, transcript)
    third = cache.tally("claude", transcript)
    assert (third.fired, third.last_skill) == (1, "gamma")
    transcript.unlink()
    assert cache.tally("claude", transcript).state != STATE_MEASURED



def _age(path: Path) -> None:
    old = os.stat(path).st_mtime - 3600
    os.utime(path, (old, old))


def _tree(tmp_path: Path):
    sessions = tmp_path / "sessions"
    days = []
    for day in ("26", "27", "28"):
        folder = sessions / "2026" / "10" / day
        folder.mkdir(parents=True)
        days.append(folder)
    (days[0] / f"rollout-2026-10-26T09-00-00-{UUID_A}.jsonl").write_text("{}\n")
    (days[1] / "notes.txt").write_text("x")
    projects = tmp_path / "projects" / "-x"
    projects.mkdir(parents=True)
    (projects / f"{UUID_B}.jsonl").write_text("{}\n")
    for folder in [*days, projects, sessions / "2026" / "10", sessions / "2026", sessions,
                   projects.parent]:
        _age(folder)
    return sessions, projects.parent, days, projects


def _listed(monkeypatch, root: Path) -> List[str]:
    seen: List[str] = []
    real = os.scandir

    def counting(path: Any = "."):
        if str(path).startswith(str(root)):
            seen.append(str(path))
        return real(path)

    monkeypatch.setattr(os, "scandir", counting)
    return seen


def _fresh_entries(roots) -> dict:
    index = fs_event_index.FsEventIndex(roots)
    index._scan()
    return dict(index._entries)


def test_the_index_walk_lists_a_folder_again_only_when_the_folder_changed(tmp_path, monkeypatch):
    sessions, projects, days, project = _tree(tmp_path)
    roots = [str(sessions), str(projects)]
    index = fs_event_index.FsEventIndex(roots)
    index._scan()
    assert index.lookup(UUID_A) == str(days[0] / f"rollout-2026-10-26T09-00-00-{UUID_A}.jsonl")
    listed = _listed(monkeypatch, tmp_path)
    index._scan()
    assert listed == [], "an unchanged tree must not be listed again"
    assert dict(index._entries) == _fresh_entries(roots)
    rollout = days[0] / f"rollout-2026-10-26T09-00-00-{UUID_A}.jsonl"
    rollout.write_text("{}\n" * 40)
    listed.clear()
    index._scan()
    assert listed == []
    assert index.entry(UUID_A)[1] == rollout.stat().st_size
    late = days[1] / f"rollout-2026-10-27T09-00-00-{UUID_B}.jsonl"
    late.write_text("{}\n")
    newday = sessions / "2026" / "10" / "29"
    newday.mkdir()
    other = "019a1b2c-3d4e-5f60-7182-93a4b5c6d7ff"
    (newday / f"rollout-2026-10-29T09-00-00-{other}.jsonl").write_text("{}\n")
    listed.clear()
    index._scan()
    assert index.lookup(UUID_B, fs_event_index.CODEX) == str(late)
    assert index.lookup(other) == str(newday / f"rollout-2026-10-29T09-00-00-{other}.jsonl")
    assert str(days[1]) in listed and str(newday) in listed and str(days[2]) not in listed
    assert dict(index._entries) == _fresh_entries(roots)
    late.unlink()
    for child in newday.iterdir():
        child.unlink()
    newday.rmdir()
    index._scan()
    assert index.lookup(UUID_B, fs_event_index.CODEX) is None and index.lookup(other) is None
    assert dict(index._entries) == _fresh_entries(roots)
    import shutil
    shutil.rmtree(sessions)
    index._scan()
    assert index.lookup(UUID_A) is None
    assert dict(index._entries) == _fresh_entries(roots)


def test_a_folder_changed_inside_the_racy_window_is_never_trusted(tmp_path, monkeypatch):
    sessions, projects, days, _project = _tree(tmp_path)
    roots = [str(sessions), str(projects)]
    index = fs_event_index.FsEventIndex(roots)
    (days[2] / f"rollout-2026-10-28T09-00-00-{UUID_B}.jsonl").write_text("{}\n")
    index._scan()
    listed = _listed(monkeypatch, tmp_path)
    index._scan()
    assert str(days[2]) in listed, "a folder inside the racy window must be listed again"

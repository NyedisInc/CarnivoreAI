
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Callable, List

import pytest

from src.core.skill_fires.scan import scan_file
from src.core.skill_fires.store import SkillFireStore
from src.core.skill_watch.spans import advance, new_state
from src.core.skill_watch.store import SkillWatchStore
from src.core.skill_watch.tripwire import TripwireProbe


def _d(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"))


def _bash(ts: str, command: str, *, sidechain: bool = False) -> str:
    record = {"type": "assistant", "timestamp": ts, "message": {"id": ts, "content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": command}}]}}
    return _d({**record, "isSidechain": True} if sidechain else record)


def _fire(ts: str) -> str:
    return _d({"type": "assistant", "timestamp": ts, "cwd": "/work/a", "message": {"id": ts, "content": [
        {"type": "tool_use", "name": "Skill", "input": {"skill": "review"}}]}})


def _write(path: Path, lines: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def _append(path: Path, line: str) -> None:
    with open(path, "a") as handle:
        handle.write(line + "\n")


@pytest.fixture()
def counted_opens(monkeypatch) -> Callable[[], int]:
    seen: List[str] = []
    real = os.open

    def spy(path, *args, **kwargs):
        if "/subagents/" in os.fspath(path):
            seen.append(os.fspath(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy)

    def take() -> int:
        count = len(seen)
        seen.clear()
        return count

    return take


@pytest.fixture()
def open_span(tmp_path: Path):
    main = tmp_path / "p" / "conv.jsonl"
    _write(main, [_fire("2026-09-28T10:00:00Z")])
    folder = main.parent / "conv" / "subagents"
    for n in range(3):
        _write(folder / f"agent-a{n}.jsonl", [_bash("2026-09-28T10:00:03Z", "ls", sidechain=True)])
    return main, folder


def test_an_idle_pass_opens_no_subagent_file(open_span, counted_opens) -> None:
    main, _ = open_span
    state = new_state(0)
    assert advance(str(main), state) and counted_opens() == 3
    assert advance(str(main), state) and counted_opens() == 0
    assert advance(str(main), state) and counted_opens() == 0


def test_an_appended_line_is_still_seen_from_where_it_left_off(open_span, counted_opens) -> None:
    main, folder = open_span
    state = new_state(0)
    advance(str(main), state)
    counted_opens()
    _append(folder / "agent-a1.jsonl", _bash("2026-09-28T10:00:04Z", "curl x.test", sidechain=True))
    assert advance(str(main), state) and counted_opens() == 1
    assert state.facts.categories.get("network") == 1


def test_a_new_subagent_file_is_read(open_span, counted_opens) -> None:
    main, folder = open_span
    state = new_state(0)
    advance(str(main), state)
    _write(folder / "agent-new.jsonl", [_bash("2026-09-28T10:00:05Z", "curl x.test", sidechain=True)])
    assert advance(str(main), state) and state.facts.categories.get("network") == 1


def test_a_replaced_file_is_re_read_even_at_the_same_size_and_mtime(open_span) -> None:
    main, folder = open_span
    target = folder / "agent-a1.jsonl"
    state = new_state(0)
    advance(str(main), state)
    stamp = target.stat()
    replacement = folder / "swap.tmp"
    replacement.write_text(_bash("2026-09-28T10:00:03Z", "ls", sidechain=True).replace("ls", "rm") + "\n")
    assert replacement.stat().st_size == stamp.st_size
    os.utime(replacement, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    os.replace(replacement, target)
    advance(str(main), state)
    assert state.facts.categories.get("file_delete") == 1


def test_a_second_idle_scan_now_makes_no_skill_watch_connection(tmp_path: Path, monkeypatch) -> None:
    fires = SkillFireStore(tmp_path / "f.db")
    watch = SkillWatchStore(tmp_path / "w.db")
    main = tmp_path / "p" / "conv.jsonl"
    _write(main, [_fire("2026-09-28T10:00:00Z")])
    scan_file(fires, str(main), "claude", "default")
    probe = TripwireProbe(fires, watch, lambda s, c: frozenset(), started_at="2026-09-28T09:00:00")
    probe.scan_now(str(main), "claude")
    connects: List[str] = []
    real = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda target, *a, **k: (
        connects.append(str(target)), real(target, *a, **k))[1])
    probe.scan_now(str(main), "claude")
    assert [c for c in connects if c.endswith("w.db")] == []


def test_the_cursor_cache_follows_the_writer(tmp_path: Path) -> None:
    watch = SkillWatchStore(tmp_path / "w.db")
    assert watch.tripwire_offset("/t.jsonl") is None
    watch.set_tripwire_offset("/t.jsonl", 5)
    assert watch.tripwire_offset("/t.jsonl") == 5
    watch.set_tripwire_offset("/t.jsonl", 9)
    assert watch.tripwire_offset("/t.jsonl") == 9


def test_a_failed_open_is_retried_on_the_next_pass(open_span, monkeypatch) -> None:
    main, folder = open_span
    _write(folder / "agent-a1.jsonl", [_bash("2026-09-28T10:00:03Z", "curl x.test", sidechain=True)])
    real = os.open
    monkeypatch.setattr(os, "open", lambda p, *a, **k: (_ for _ in ()).throw(OSError(24, "EMFILE"))
                        if "/subagents/" in os.fspath(p) else real(p, *a, **k))
    state = new_state(0)
    advance(str(main), state)
    assert state.facts.categories.get("network") is None
    monkeypatch.setattr(os, "open", real)
    advance(str(main), state)
    assert state.facts.categories.get("network") == 1


def test_only_the_failed_file_is_retried(open_span, monkeypatch) -> None:
    main, folder = open_span
    real, attempts = os.open, []
    target = str(folder / "agent-a1.jsonl")

    def flaky(path, *args, **kwargs):
        if "/subagents/" in os.fspath(path):
            attempts.append(os.path.basename(os.fspath(path)))
        if os.fspath(path) == target:
            raise OSError(24, "EMFILE")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", flaky)
    state = new_state(0)
    advance(str(main), state)
    attempts.clear()
    advance(str(main), state)
    assert attempts == ["agent-a1.jsonl"]


def test_a_truncated_and_rewritten_file_is_read_from_the_start(open_span) -> None:
    main, folder = open_span
    target = folder / "agent-a1.jsonl"
    _append(target, _bash("2026-09-28T10:00:04Z", "ls", sidechain=True))
    state = new_state(0)
    advance(str(main), state)
    _write(target, [_bash("2026-09-28T10:00:06Z", "rm x", sidechain=True)])
    assert target.stat().st_size < state.subs[str(target)][1]
    advance(str(main), state)
    assert state.facts.categories.get("file_delete") == 1


def test_a_deleted_then_recreated_file_is_read(open_span) -> None:
    main, folder = open_span
    state = new_state(0)
    advance(str(main), state)
    (folder / "agent-a1.jsonl").unlink()
    advance(str(main), state)
    _write(folder / "agent-a1.jsonl", [_bash("2026-09-28T10:00:07Z", "curl y.test", sidechain=True)])
    advance(str(main), state)
    assert state.facts.categories.get("network") == 1


def test_a_closing_span_still_gets_its_final_pass_over_unchanged_files(open_span) -> None:
    main, folder = open_span
    _append(folder / "agent-a1.jsonl", _bash("2026-09-28T10:00:20Z", "curl late.test", sidechain=True))
    state = new_state(0)
    advance(str(main), state)
    assert state.facts.categories.get("network") == 1
    _append(main, _d({"type": "user", "timestamp": "2026-09-28T10:00:09Z", "message": {"content": "thanks"}}))
    advance(str(main), state)
    assert state.done and state.subs_final and state.facts.categories.get("network") == 1


def test_a_meta_file_change_opens_nothing(open_span, counted_opens) -> None:
    main, folder = open_span
    state = new_state(0)
    advance(str(main), state)
    counted_opens()
    (folder / "agent-a1.meta.json").write_text("{}")
    advance(str(main), state)
    assert counted_opens() == 0

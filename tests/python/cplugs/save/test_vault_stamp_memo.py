
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Dict, List, Tuple

from src.cplugs.save.vault import units
from src.cplugs.save.vault.stamp_memo import StampMemo
from src.cplugs.save.vault.workdirs import WorkingDirMemo
from tests.python.cplugs.save.vault_helpers import CODEX_ID, CONV, ENC, World, jsonl

HOUR_NS = 3600 * 10 ** 9


def settled_memo(max_entries: int = 60_000) -> StampMemo:
    return StampMemo(max_entries, clock_ns=lambda: time.time_ns() + HOUR_NS)


def shape(plans: Dict[str, units.UnitPlan]) -> Dict[str, List[Tuple[str, str, str, str]]]:
    return {unit: [(str(f.path), f.role, f.home, f.rel) for f in plan.files] for unit, plan in plans.items()}


def test_a_folder_changed_a_moment_ago_is_not_trusted(tmp_path):
    (tmp_path / "a").write_text("x")
    memo = StampMemo()
    builds = []
    for _ in range(3):
        memo.get(tmp_path, "k", lambda: builds.append(1) or ["a"])
    assert len(builds) == 3


def test_a_settled_folder_is_built_once_and_again_when_it_changes(tmp_path):
    (tmp_path / "a").write_text("x")
    memo = settled_memo()
    builds = []
    build = lambda: builds.append(1) or sorted(os.listdir(tmp_path))  # noqa: E731
    assert memo.get(tmp_path, "k", build) == memo.get(tmp_path, "k", build) == ["a"]
    assert len(builds) == 1
    (tmp_path / "b").write_text("y")
    assert memo.get(tmp_path, "k", build) == ["a", "b"] and len(builds) == 2


def test_a_value_that_could_not_be_built_is_not_kept(tmp_path):
    memo = settled_memo()
    state = {"fail": True}

    def build() -> List[str]:
        if state["fail"]:
            raise PermissionError("not yet")
        return ["ok"]

    try:
        memo.get(tmp_path, "k", build)
    except PermissionError:
        pass
    state["fail"] = False
    assert memo.get(tmp_path, "k", build) == ["ok"]


def test_the_memo_drops_its_oldest_values_to_stay_inside_its_bound(tmp_path):
    memo = settled_memo(max_entries=5)
    folders = []
    for n in range(4):
        folder = tmp_path / f"f{n}"
        folder.mkdir()
        folders.append(folder)
        memo.get(folder, "k", lambda: [1, 2])
    builds = []
    memo.get(folders[0], "k", lambda: builds.append(1) or [1, 2])
    memo.get(folders[3], "k", lambda: builds.append(1) or [1, 2])
    assert len(builds) == 1


def messy_world(tmp_path: Path) -> World:
    world = World(tmp_path)
    world.write_conversation(jsonl(5), subagents=3, tool_results=2)
    folder = world.transcript().parent / CONV
    (folder / "workflows" / "run-1" / "deep").mkdir(parents=True)
    (folder / "workflows" / "run-1" / "deep" / "step.json").write_text("{}")
    (folder / "subagents" / "link.jsonl").symlink_to(folder / "subagents" / "agent-0.jsonl")
    (folder / "linked-dir").symlink_to(folder / "workflows", target_is_directory=True)
    os.mkfifo(folder / "tool-results" / "pipe")
    memory = world.transcript().parent / "memory"
    memory.mkdir()
    (memory / "MEMORY.md").write_text("notes")
    side = world.transcript().parent / "_from-other" / "memory"
    side.mkdir(parents=True)
    (side / "x.md").write_text("merged")
    world.write_codex(jsonl(3))
    return world


def test_a_plan_made_from_the_memory_is_the_plan_a_fresh_walk_makes(tmp_path):
    world = messy_world(tmp_path)
    memo = settled_memo()
    folder = world.transcript().parent / CONV
    assert shape(units.scan_all(world.sources, units.Scanner(world.sources, memo))) == shape(units.scan_all(world.sources))
    (folder / "subagents" / "agent-9.jsonl").write_text("new\n")
    (folder / "tool-results" / "t0.txt").unlink()
    (folder / "workflows" / "run-2").mkdir()
    (folder / "workflows" / "run-2" / "later.json").write_text("{}")
    (world.home / "file-history" / CONV / "def@v2").write_text("history")
    world.write_codex(jsonl(2), thread=CODEX_ID[:-1] + "2", day="2026/03/02")
    after = shape(units.scan_all(world.sources))
    assert shape(units.scan_all(world.sources, units.Scanner(world.sources, memo))) == after
    assert shape(units.scan_all(world.sources, units.Scanner(world.sources, memo))) == after
    rels = {rel for _p, _r, _h, rel in after[CONV]}
    assert f"projects/{ENC}/{CONV}/subagents/agent-9.jsonl" in rels and not any("link" in rel for rel in rels)


def test_a_folder_that_could_not_be_read_is_planned_when_it_can_again(tmp_path):
    world = messy_world(tmp_path)
    memo = settled_memo()
    hidden = world.transcript().parent / CONV / "tool-results"
    hidden.chmod(0)
    try:
        without = shape(units.scan_all(world.sources, units.Scanner(world.sources, memo)))
    finally:
        hidden.chmod(0o755)
    with_it = shape(units.scan_all(world.sources, units.Scanner(world.sources, memo)))
    assert not any("tool-results" in rel for _p, _r, _h, rel in without[CONV])
    assert any("tool-results" in rel for _p, _r, _h, rel in with_it[CONV])


def write_cwd(path: Path, cwd: str) -> None:
    path.write_text('{"type":"user","cwd":"%s"}\n' % cwd + jsonl(3).decode())


def test_a_working_folder_is_read_once_per_file(tmp_path, monkeypatch):
    path = tmp_path / "a.jsonl"
    write_cwd(path, "/Users/x/app")
    opened: List[str] = []
    real = units.peek_working_dir
    monkeypatch.setattr("src.cplugs.save.vault.workdirs.peek_working_dir", lambda p: opened.append(str(p)) or real(p))
    memo = WorkingDirMemo()
    assert [memo.get(path) for _ in range(3)] == ["/Users/x/app"] * 3
    with open(path, "ab") as handle:
        handle.write(jsonl(2))
    assert memo.get(path) == "/Users/x/app" and len(opened) == 1


def test_a_working_folder_is_read_again_for_a_replaced_or_shortened_file(tmp_path):
    path = tmp_path / "a.jsonl"
    write_cwd(path, "/Users/x/one")
    memo = WorkingDirMemo()
    assert memo.get(path) == "/Users/x/one"
    other = tmp_path / "b.jsonl"
    write_cwd(other, "/Users/x/two")
    os.replace(other, path)
    assert memo.get(path) == "/Users/x/two"
    with open(path, "r+b") as handle:
        handle.truncate(0)
        handle.write(b'{"cwd":"/Users/x/3"}\n')
    assert memo.get(path) == "/Users/x/3"


def test_a_transcript_with_no_working_folder_yet_is_asked_again(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text('{"type":"user"}\n')
    memo = WorkingDirMemo()
    assert memo.get(path) is None
    with open(path, "ab") as handle:
        handle.write(b'{"cwd":"/Users/x/late"}\n')
    assert memo.get(path) == "/Users/x/late"
    assert memo.get(None) is None and memo.get(tmp_path / "missing.jsonl") is None

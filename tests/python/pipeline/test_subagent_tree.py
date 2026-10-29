
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List

from src.core.pipeline import subagent_tree
from src.core.pipeline.observe import Observer
from src.core.pipeline.subagent_tree import SubagentTreeIndex


def _age(root: Path) -> None:
    old = time.time() - 3600
    for dirpath, _dirs, files in os.walk(root, topdown=False):
        os.utime(dirpath, (old, old))


def _glob(root: Path) -> List[str]:
    return [str(p) for p in sorted(root.rglob("*.jsonl"))]


def test_matches_rglob_through_adds_removes_and_nesting(tmp_path: Path) -> None:
    root = tmp_path / "subagents"
    (root / "workflows" / "wf_1").mkdir(parents=True)
    (root / "agent-1.jsonl").write_text("x")
    (root / "agent-1.meta.json").write_text("{}")
    (root / "workflows" / "wf_1" / "agent-2.jsonl").write_text("x")
    index = SubagentTreeIndex()
    assert index.list_jsonl(str(root)) == _glob(root)
    _age(root)
    index.list_jsonl(str(root))
    (root / "workflows" / "wf_1" / "agent-3.jsonl").write_text("x")
    _age(root / "workflows")
    os.utime(root / "workflows" / "wf_1", (time.time() - 10, time.time() - 10))
    assert index.list_jsonl(str(root)) == _glob(root)
    (root / "agent-1.jsonl").unlink()
    os.utime(root, (time.time() - 5, time.time() - 5))
    assert index.list_jsonl(str(root)) == _glob(root)
    (root / "workflows" / "wf_1").rename(root / "workflows" / "wf_9")
    assert index.list_jsonl(str(root)) == _glob(root)
    assert not any("wf_1" in p for p in index._dirs)


def test_unchanged_trusted_directories_are_not_rescanned(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "subagents"
    (root / "workflows" / "wf_1").mkdir(parents=True)
    (root / "agent-1.jsonl").write_text("x")
    _age(root)
    index = SubagentTreeIndex()
    index.list_jsonl(str(root))
    expected = _glob(root)
    calls: List[str] = []
    real = os.scandir
    monkeypatch.setattr(subagent_tree.os, "scandir", lambda p: (calls.append(str(p)), real(p))[1])
    assert index.list_jsonl(str(root)) == expected
    assert calls == []


def test_fresh_directory_mtime_is_never_trusted(tmp_path: Path) -> None:
    root = tmp_path / "subagents"
    root.mkdir()
    index = SubagentTreeIndex()
    index.list_jsonl(str(root))
    (root / "agent-1.jsonl").write_text("x")
    assert index.list_jsonl(str(root)) == _glob(root)


def test_index_is_bounded(tmp_path: Path) -> None:
    index = SubagentTreeIndex(max_dirs=2)
    for n in range(4):
        (tmp_path / ("d%d" % n) / "workflows" / "wf").mkdir(parents=True)
        index.list_jsonl(str(tmp_path / ("d%d" % n)))
    assert len(index._dirs) <= 2


def test_observer_marks_new_and_grown_subagent_files(tmp_path: Path) -> None:
    root = tmp_path / "c1" / "subagents"
    root.mkdir(parents=True)
    marked: List[str] = []
    obs = Observer(lambda target, trigger: marked.append(target.path) or True)
    f = root / "agent-1.jsonl"
    f.write_text("a")
    assert obs.session_changed(None, str(root)) == 1
    assert obs.session_changed(None, str(root)) == 0
    f.write_text("ab")
    assert obs.session_changed(None, str(root)) == 1
    (root / "agent-2.jsonl").write_text("z")
    assert obs.session_changed(None, str(root)) == 1

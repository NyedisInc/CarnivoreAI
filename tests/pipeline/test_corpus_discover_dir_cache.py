
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List

import pytest

from src.core import transcript_corpus_discover as D
from src.core.pipeline.contract import FILE_CONVERSATION, FILE_SUBAGENT, Plugin


def _age(path: Path, seconds: int = 3600) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


def _corpus(tmp_path: Path) -> Path:
    sub = tmp_path / "slug" / "uuid" / "subagents"
    sub.mkdir(parents=True)
    (tmp_path / "slug" / "uuid.jsonl").write_text("{}\n")
    (sub / "agent-1.jsonl").write_text("{}\n")
    (sub / "note.txt").write_text("x")
    for d in (sub, sub.parent, sub.parent.parent, tmp_path):
        _age(d)
    return tmp_path


def _paths(outcome: D.DiscoveryOutcome) -> List[str]:
    return sorted(e.source_path for e in outcome.entries)


@pytest.fixture()
def iterdir_calls(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    calls: List[str] = []
    real = Path.iterdir

    def counting(self: Path):
        calls.append(str(self))
        return real(self)

    monkeypatch.setattr(Path, "iterdir", counting)
    return calls


def test_unchanged_tree_does_no_iterdir_on_second_pass(tmp_path: Path, iterdir_calls: List[str]) -> None:
    root, cache = _corpus(tmp_path), D.DirListingCache()
    first = D.discover_corpus_detailed(root, cache)
    assert iterdir_calls, "the first pass must list directories"
    iterdir_calls.clear()
    second = D.discover_corpus_detailed(root, cache)
    assert iterdir_calls == []
    assert _paths(second) == _paths(first) == ["slug/uuid.jsonl", "slug/uuid/subagents/agent-1.jsonl"]
    assert second.unrecognised_count == first.unrecognised_count == 1


def test_new_subagent_file_is_picked_up_next_pass(tmp_path: Path) -> None:
    root, cache = _corpus(tmp_path), D.DirListingCache()
    D.discover_corpus_detailed(root, cache)
    sub = root / "slug" / "uuid" / "subagents"
    (sub / "agent-2.jsonl").write_text("{}\n")
    assert "slug/uuid/subagents/agent-2.jsonl" in _paths(D.discover_corpus_detailed(root, cache))


def test_new_session_and_new_directory_are_picked_up(tmp_path: Path) -> None:
    root, cache = _corpus(tmp_path), D.DirListingCache()
    D.discover_corpus_detailed(root, cache)
    (root / "slug" / "other.jsonl").write_text("{}\n")
    nested = root / "slug2" / "u2" / "subagents" / "workflows" / "wf_1"
    nested.mkdir(parents=True)
    (nested / "a.jsonl").write_text("{}\n")
    found = _paths(D.discover_corpus_detailed(root, cache))
    assert "slug/other.jsonl" in found
    assert "slug2/u2/subagents/workflows/wf_1/a.jsonl" in found


def test_removed_file_disappears_next_pass(tmp_path: Path) -> None:
    root, cache = _corpus(tmp_path), D.DirListingCache()
    D.discover_corpus_detailed(root, cache)
    (root / "slug" / "uuid" / "subagents" / "agent-1.jsonl").unlink()
    assert "slug/uuid/subagents/agent-1.jsonl" not in _paths(D.discover_corpus_detailed(root, cache))


def test_recently_changed_directory_is_never_trusted(tmp_path: Path, iterdir_calls: List[str]) -> None:
    root, cache = _corpus(tmp_path), D.DirListingCache()
    sub = root / "slug" / "uuid" / "subagents"
    os.utime(sub, None)
    D.discover_corpus_detailed(root, cache)
    iterdir_calls.clear()
    D.discover_corpus_detailed(root, cache)
    assert str(sub) in iterdir_calls


def test_cached_result_equals_uncached(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    plain = D.discover_corpus_detailed(root)
    cached = D.discover_corpus_detailed(root, D.DirListingCache())
    assert _paths(plain) == _paths(cached)
    assert plain.unrecognised_sample == cached.unrecognised_sample


def test_reads_snapshot_asks_the_kinds_function_once() -> None:
    asked: List[int] = []

    def kinds() -> frozenset:
        asked.append(1)
        return frozenset({FILE_CONVERSATION})

    plugin = Plugin.__new__(Plugin)
    object.__setattr__(plugin, "families", ("claude",))
    object.__setattr__(plugin, "file_kinds", frozenset({FILE_CONVERSATION, FILE_SUBAGENT}))
    object.__setattr__(plugin, "file_kinds_fn", kinds)
    reads = plugin.reads_snapshot()
    results = [reads("claude", FILE_CONVERSATION) for _ in range(50)] + [reads("claude", FILE_SUBAGENT)]
    assert asked == [1]
    assert results[:-1] == [True] * 50 and results[-1] is False


from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.bookmarks import transcript_index as ti


def _rec(n: int, parent: int | None, kind: str = "user", text: str | None = None) -> Dict[str, Any]:
    message = {"role": kind, "content": text or f"text {n}"} if kind == "user" else {"id": f"m{n}", "content": [{"type": "text", "text": f"r{n}"}]}
    return {"type": kind, "uuid": f"u{n}", "parentUuid": None if parent is None else f"u{parent}", "sessionId": "s1",
            "timestamp": f"2026-11-01T10:00:{n:02d}.000Z", "message": message}


def _write(path: Path, records: List[Dict[str, Any]], mode: str = "wb", end: bytes = b"\n") -> None:
    with open(path, mode) as handle:
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":")).encode() + end)


@pytest.fixture
def counting(monkeypatch: pytest.MonkeyPatch):
    ti._cache.clear()
    starts: List[int] = []
    real = ti._index_line
    monkeypatch.setattr(ti, "_index_line", lambda index, raw, start: (starts.append(start), real(index, raw, start))[1])
    yield starts
    ti._cache.clear()


def _same(a: ti.TranscriptIndex, b: ti.TranscriptIndex) -> None:
    assert a.nodes == b.nodes and a.order == b.order and a.children == b.children and a.carried == b.carried
    assert (a.size, a.source_session_id, a.consumed, a.skipped_lines) == (b.size, b.source_session_id, b.consumed, b.skipped_lines)


def test_an_append_reads_only_the_new_lines_and_equals_a_full_rebuild(tmp_path: Path, counting) -> None:
    path = tmp_path / "c.jsonl"
    _write(path, [_rec(1, None), _rec(2, 1, "assistant"), _rec(3, 2)])
    old = ti.cached_index(path)
    assert len(counting) == 3
    counting.clear()
    _write(path, [_rec(4, 3, "assistant"), _rec(5, 4), _rec(6, 3)], mode="ab")
    new = ti.cached_index(path)
    assert len(counting) == 3 and counting[0] == old.size
    assert len(old.nodes) == 3 and old.children == {"u1": ["u2"], "u2": ["u3"]}
    ti._cache.clear()
    _same(new, ti.cached_index(path))
    assert new.children["u3"] == ["u4", "u6"]


def test_a_rewritten_file_is_reindexed_whole(tmp_path: Path, counting) -> None:
    path = tmp_path / "c.jsonl"
    _write(path, [_rec(1, None), _rec(2, 1), _rec(3, 2)])
    ti.cached_index(path)
    counting.clear()
    _write(path, [_rec(1, None), _rec(2, 1), _rec(7, 2, text="a different third line, longer than before"), _rec(8, 7)])
    index = ti.cached_index(path)
    assert len(counting) == 4 and "u3" not in index.nodes and "u7" in index.nodes


def test_a_same_length_rewrite_of_the_last_line_is_caught_by_its_serial(tmp_path: Path, counting) -> None:
    path = tmp_path / "c.jsonl"
    _write(path, [_rec(1, None), _rec(2, 1)])
    ti.cached_index(path)
    counting.clear()
    path.write_bytes(path.read_bytes().replace(b'"uuid":"u2"', b'"uuid":"x2"'))
    _write(path, [_rec(3, 2)], mode="ab")
    index = ti.cached_index(path)
    assert len(counting) == 3 and "x2" in index.nodes and "u2" not in index.nodes


def test_a_truncated_file_and_a_torn_tail_are_not_resumed(tmp_path: Path, counting) -> None:
    path = tmp_path / "c.jsonl"
    _write(path, [_rec(1, None), _rec(2, 1), _rec(3, 2)])
    ti.cached_index(path)
    counting.clear()
    path.write_bytes(path.read_bytes()[:len(path.read_bytes()) // 2])
    assert len(ti.cached_index(path).nodes) == 1 and len(counting) >= 1
    _write(path, [_rec(5, 1)], mode="wb", end=b"")
    torn = ti.cached_index(path)
    counting.clear()
    with open(path, "ab") as handle:
        handle.write(b"\n")
    _write(path, [_rec(6, 5)], mode="ab", end=b"\n")
    ti.cached_index(path)
    assert torn.consumed != torn.size and len(counting) == 2

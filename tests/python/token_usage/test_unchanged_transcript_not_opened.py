
from __future__ import annotations

import builtins
import json
import os
from pathlib import Path
from typing import Any, List

from src.core.session_token_usage import claude_reader
from src.core.session_token_usage.cache import IncrementalCache


def _turn(n: int) -> str:
    rec = {"type": "assistant", "message": {"id": "m%d" % n, "model": "claude-x",
                                            "usage": {"input_tokens": n, "output_tokens": 1}}}
    return json.dumps(rec) + "\n"


def _cold(path: Path) -> Any:
    return claude_reader.read_transcript_totals(path, cache=IncrementalCache())


def test_unchanged_file_is_not_opened(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "c.jsonl"
    path.write_text(_turn(1) + _turn(2))
    cache = IncrementalCache()
    first = claude_reader.read_transcript_totals(path, cache=cache)
    opened: List[Any] = []
    real = builtins.open
    monkeypatch.setattr(claude_reader, "open", lambda *a, **k: (opened.append(a), real(*a, **k))[1], raising=False)
    again = claude_reader.read_transcript_totals(path, cache=cache)
    assert opened == [] and again == first


def test_append_truncate_rotate_equal_cold_read(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    cache = IncrementalCache()
    path.write_text(_turn(1))
    assert claude_reader.read_transcript_totals(path, cache=cache) == _cold(path)
    with path.open("a") as fh:
        fh.write(_turn(2) + _turn(3))
    assert claude_reader.read_transcript_totals(path, cache=cache) == _cold(path)
    path.write_text(_turn(9))
    assert claude_reader.read_transcript_totals(path, cache=cache) == _cold(path)
    other = tmp_path / "n.jsonl"
    other.write_text(_turn(5) + _turn(6) + _turn(7))
    os.replace(other, path)
    assert claude_reader.read_transcript_totals(path, cache=cache) == _cold(path)


def test_partial_line_is_not_lost_when_completed(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    line = _turn(2)
    path.write_text(_turn(1) + line[:15])
    cache = IncrementalCache()
    claude_reader.read_transcript_totals(path, cache=cache)
    with path.open("a") as fh:
        fh.write(line[15:])
    assert claude_reader.read_transcript_totals(path, cache=cache) == _cold(path)


def test_missing_file_is_none_and_cold_cap_still_applies(tmp_path: Path) -> None:
    assert claude_reader.read_transcript_totals(tmp_path / "no.jsonl", cache=IncrementalCache()) is None
    big = tmp_path / "big.jsonl"
    big.write_text(_turn(1))
    assert claude_reader.read_transcript_totals(big, cache=IncrementalCache(), max_cold_bytes=1) is None

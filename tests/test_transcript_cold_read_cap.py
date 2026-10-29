
from __future__ import annotations

import json
from pathlib import Path

from src.core.session_token_usage.cache import IncrementalCache
from src.core.session_token_usage.claude_reader import read_transcript_totals


def _transcript(tmp_path: Path, *, turns: int, pad: int = 0) -> Path:
    path = tmp_path / "transcript.jsonl"
    lines = []
    for i in range(turns):
        lines.append(json.dumps({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "id": f"m{i}",
                "model": "claude-opus-5",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
            "effort": "high",
        }))
    if pad:
        lines.append(json.dumps({"type": "summary", "filler": "x" * pad}))
    path.write_text("\n".join(lines) + "\n")
    return path


def test_no_cap_reads_the_file_however_big_it_is(tmp_path: Path) -> None:
    path = _transcript(tmp_path, turns=2, pad=5000)
    totals = read_transcript_totals(path, cache=IncrementalCache())
    assert totals is not None
    assert totals.last_model == "claude-opus-5"


def test_a_cold_read_over_the_cap_is_refused(tmp_path: Path) -> None:
    path = _transcript(tmp_path, turns=2, pad=5000)
    size = path.stat().st_size
    assert size > 1000, "the fixture must actually be bigger than the cap below"

    totals = read_transcript_totals(
        path, cache=IncrementalCache(), max_cold_bytes=1000
    )
    assert totals is None, "a cold read over the cap answers None, not a parse"


def test_a_read_UNDER_the_cap_is_unaffected(tmp_path: Path) -> None:
    path = _transcript(tmp_path, turns=1)
    totals = read_transcript_totals(
        path, cache=IncrementalCache(), max_cold_bytes=10 * 1024 * 1024
    )
    assert totals is not None
    assert totals.last_model == "claude-opus-5"


def test_A_FILE_ALREADY_CACHED_IS_STILL_READ_WHEN_IT_OUTGROWS_THE_CAP(
    tmp_path: Path,
) -> None:
    cache = IncrementalCache()
    path = _transcript(tmp_path, turns=1)
    first = read_transcript_totals(path, cache=cache, max_cold_bytes=10_000)
    assert first is not None and first.last_model == "claude-opus-5"

    with path.open("a") as fh:
        fh.write(json.dumps({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "id": "m99",
                "model": "claude-sonnet-5",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        }) + "\n")
        fh.write(json.dumps({"type": "summary", "filler": "x" * 20_000}) + "\n")
    assert path.stat().st_size > 10_000

    second = read_transcript_totals(path, cache=cache, max_cold_bytes=10_000)
    assert second is not None, "a cached file must resume however large it grew"
    assert second.last_model == "claude-sonnet-5", "and must see the new tail"


def test_an_unreadable_path_answers_none_rather_than_raising(tmp_path: Path) -> None:
    missing = tmp_path / "not-here.jsonl"
    assert read_transcript_totals(missing, max_cold_bytes=10) is None

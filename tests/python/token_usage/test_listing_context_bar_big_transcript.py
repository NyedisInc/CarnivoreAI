
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.session_token_usage import claude_reader, listing_model_facts as lmf
from src.core.session_token_usage.listing_model_facts import (
    ModelListingFacts, build_model_listing_prefetch,
)
from src.core.session_token_usage.model_table import window_for_model
from tests.test_session_row_model import (
    EPOCH, NAME, _index_with, _prefetch_with,
)
from tests.test_session_token_usage import UUID, _assistant, _claude_corpus

_SMALL_CAP = 4 * 1024
_FILLER = json.dumps({"type": "summary", "filler": "x" * (260 * 1024)})
_HUGE_FILLER = json.dumps({"type": "summary", "filler": "x" * (5 * 1024 * 1024)})
_BIG_LAST_LINE = json.dumps({"type": "user", "filler": "x" * (300 * 1024)})


def _facts_for(corpus: Path, monkeypatch: pytest.MonkeyPatch) -> ModelListingFacts:
    monkeypatch.setattr(lmf, "MAX_COLD_TRANSCRIPT_BYTES", _SMALL_CAP)
    real = lmf.read_session_token_usage
    monkeypatch.setattr(
        lmf, "read_session_token_usage",
        lambda subject, projects_dir=None, codex_home=None, max_cold_bytes=None: real(
            subject, projects_dir=corpus, codex_home=codex_home,
            max_cold_bytes=max_cold_bytes,
        ),
    )
    facts = build_model_listing_prefetch(
        names=[NAME],
        status_map={NAME: {"created_at_epoch": EPOCH}},
        instance_index=_index_with(NAME, EPOCH, UUID, "/tmp/project"),
        prefetch=_prefetch_with(NAME, "claude"),
    )
    return facts[NAME]


def test_huge_transcript_still_gets_context_pct_from_its_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    turn = _assistant("msg_t", "claude-opus-5", inp=1000, cache_creation=2000,
                      cache_read=3000, out=50)
    corpus = _claude_corpus(tmp_path, [_FILLER, json.dumps(turn)])
    entry = _facts_for(corpus, monkeypatch)
    window = window_for_model("claude-opus-5")
    assert entry.model == "claude-opus-5"
    assert entry.context_used_pct == pytest.approx(6000 / window * 100.0)


def test_huge_transcript_with_no_usage_in_the_tail_stays_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    turn = _assistant("msg_t", "claude-opus-5", inp=1000, cache_creation=0,
                      cache_read=0, out=5)
    corpus = _claude_corpus(tmp_path, [json.dumps(turn), _HUGE_FILLER])
    entry = _facts_for(corpus, monkeypatch)
    assert entry.context_used_pct is None
    assert entry.model is None


def test_usage_line_before_a_big_last_line_is_still_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turn = _assistant("msg_t", "claude-opus-5", inp=1000, cache_creation=2000,
                      cache_read=3000, out=50)
    corpus = _claude_corpus(tmp_path, [json.dumps(turn), _BIG_LAST_LINE])
    entry = _facts_for(corpus, monkeypatch)
    assert entry.context_used_pct == pytest.approx(6000 / window_for_model("claude-opus-5") * 100.0)


def test_unchanged_file_with_no_usage_in_its_tail_is_read_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text(_HUGE_FILLER + "\n")
    opens: list[str] = []
    real_open = open

    def counting_open(file, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if str(file) == str(path):
            opens.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(claude_reader, "open", counting_open, raising=False)
    first = claude_reader.read_transcript_tail_totals(path)
    after_first = len(opens)
    second = claude_reader.read_transcript_tail_totals(path)
    assert first is not None and first.last_usage is None
    assert after_first >= 1
    assert len(opens) == after_first and second is first


def test_a_repeated_read_failure_warns_once_then_drops_to_debug() -> None:
    from structlog.testing import capture_logs

    lmf._SEEN_FAILURES.clear()
    with capture_logs() as logs:
        for _ in range(3):
            lmf._log_read_failure("cloude_throttle", "KeyError")
        lmf._log_read_failure("cloude_throttle", "ValueError")
    levels = [entry["log_level"] for entry in logs]
    assert levels == ["warning", "debug", "debug", "warning"]


def test_a_growing_file_skips_to_the_remembered_window_then_drops_back_when_usage_is_near_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turn = _assistant("msg_t", "claude-opus-5", inp=1000, cache_creation=0, cache_read=0, out=5)
    path = tmp_path / "live.jsonl"
    path.write_text("\n".join([json.dumps(turn), _BIG_LAST_LINE, _BIG_LAST_LINE, _BIG_LAST_LINE]) + "\n")
    windows: list[int] = []
    real_scan = claude_reader._tail_window_totals

    def spy(target: Path, tail_bytes: int):  # noqa: ANN202
        windows.append(tail_bytes)
        return real_scan(target, tail_bytes)

    def append(line: str) -> None:
        with path.open("a") as handle:
            handle.write(line + "\n")

    monkeypatch.setattr(claude_reader, "_tail_window_totals", spy)
    claude_reader._WINDOW_HINTS.clear()
    small = claude_reader.TAIL_READ_BYTES
    assert claude_reader.read_transcript_tail_totals(path).last_usage is not None
    assert windows == [small, small * 2, small * 4]
    windows.clear()
    append(json.dumps({"type": "user", "filler": "y" * 100}))
    assert claude_reader.read_transcript_tail_totals(path).last_usage is not None
    assert windows == [small, small * 4], "after a miss at the small window, jump to the window that worked"
    windows.clear()
    append(json.dumps(turn))
    assert claude_reader.read_transcript_tail_totals(path).last_usage is not None
    assert windows == [small], "a read must drop back to the small window once usage is near the end"
    windows.clear()
    append(_BIG_LAST_LINE)
    claude_reader.read_transcript_tail_totals(path)
    assert windows[0] == small and windows[-1] <= small * 2

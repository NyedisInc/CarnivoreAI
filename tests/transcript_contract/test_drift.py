
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.transcript_contract import DriftTally, parse_claude_line, parse_codex_line
from tests.transcript_contract.fixture_lines import load

REAL_ENV = "CARNIVORE_TRANSCRIPT_DRIFT"
NEWEST_FILES = 60


def _tally_fixtures() -> DriftTally:
    tally = DriftTally()
    for row in load("claude"):
        tally.observe(parse_claude_line(row["line"]))
    for row in load("codex"):
        tally.observe(parse_codex_line(row["line"]))
    return tally


def test_fixtures_report_no_new_shape() -> None:
    tally = _tally_fixtures()
    assert tally.new_shapes == {}
    assert sum(tally.lines.values()) == len(load("claude")) + len(load("codex"))


def test_a_novel_shape_turns_the_report_red() -> None:
    tally = _tally_fixtures()
    tally.observe(parse_claude_line('{"type":"time-crystal","sessionId":"<str>"}'))
    tally.observe(parse_claude_line('{"type":"mode","mode":"<str>","sessionId":"<str>","newKey":1}'))
    tally.observe(parse_codex_line('{"timestamp":"t","type":"event_msg","payload":{"type":"nova"}}'))
    assert tally.new_shapes == {
        "claude:time-crystal:unknown_type:record:time-crystal": 1,
        "claude:mode:extra_key:newKey": 1,
        "codex:event_msg:nova:unknown_type:codex_payload:event_msg:nova": 1,
    }
    assert tally.kinds["claude:time-crystal:unknown"] == 1


def _newest(paths: list) -> list:
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)[:NEWEST_FILES]


@pytest.mark.real_transcripts
def test_real_transcripts_have_no_new_shape() -> None:
    if os.environ.get(REAL_ENV) != "1":
        pytest.skip(f"real-file drift pass is opt in: set {REAL_ENV}=1")
    from scripts.transcript_contract.walk import (
        claude_files, codex_files, is_dataless, read_text_lines,
    )

    claude_root = Path("~/.claude/projects").expanduser()
    codex_root = Path("~/.codex/sessions").expanduser()
    found = claude_files(claude_root) if claude_root.is_dir() else []
    picks = [("claude", p) for p in _newest([p for p, s in found if s == "main"])]
    picks += [("claude", p) for p in _newest([p for p, s in found if s != "main"])]
    if codex_root.is_dir():
        picks += [("codex", p) for p in _newest(codex_files(codex_root))]
    picks = [(fam, p) for fam, p in picks if not is_dataless(p)]
    if not picks:
        pytest.skip("no transcript or rollout file on this machine")
    tally = DriftTally()
    for family, path in picks:
        parse = parse_claude_line if family == "claude" else parse_codex_line
        for status, text in read_text_lines(path):
            if text is None:
                tally.observe_status(family, status)
            else:
                tally.observe(parse(text))
    assert sum(tally.lines.values()) > 0, "read no line at all"
    assert tally.new_shapes == {}, tally.new_shapes

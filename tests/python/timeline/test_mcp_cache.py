
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.attention.transcript_facts import read_transcript_facts
from src.core.mcp_health.fold import McpEvent, fold_mcp_health
from src.core.mcp_health.history import HistoryEntry, join_history, reset_history
from src.core.timeline.context import ExtractContext
from src.core.timeline.extract import extract_line
from src.core.timeline.facts_adapter import TURN_END_FIELDS, WholeFileUnavailableError, facts_from_state
from src.core.timeline.fold import ConvState, fold_record
from src.core.timeline.mcp_log import McpLog
from tests.python.timeline.fold_fixtures import (
    CONV, NOW, TAIL, assistant, build, call, differences, mcp_removed, pad, result, turn_end, user, write,
)

PARITY = Path(__file__).resolve().parents[3] / "scripts" / "timeline" / "fold_parity.py"


def _heal_then_scroll() -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = [mcp_removed(1), user(2, "go"), assistant(3, [call("m_1", "mcp__other__first")]), result(4, "m_1")]
    records += [pad(10 + i, i) for i in range(14)]
    records += [mcp_removed(60), assistant(61, [call("m_2", "mcp__demo__second")]), result(62, "m_2")]
    records += [pad(80 + i, 20 + i) for i in range(14)] + [turn_end(120)]
    return records


def _steady(tmp_path: Path, every: int) -> List[str]:
    lines = write(tmp_path / "full.jsonl", _heal_then_scroll())
    live = tmp_path / "live.jsonl"
    state, ctx, bad = ConvState(conv=CONV), ExtractContext(conv=CONV), []
    reset_history()
    for number, (record, raw, end) in enumerate(lines, start=1):
        fold_record(state, record, extract_line(ctx, raw, end), end)
        if number % every and number != len(lines):
            continue
        live.write_bytes(b"".join(r + b"\n" for _rec, r, _e in lines[:number]))
        want = read_transcript_facts(str(live), tail_bytes=TAIL, wide_tail_bytes=1 << 20, now=NOW)
        got = facts_from_state(state, now=NOW, size=end, tail_bytes=TAIL, wide_tail_bytes=1 << 20)
        bad += [f"@{number} {d}" for d in differences(got, want, TURN_END_FIELDS if want.turn_end_kind is None else frozenset())]
    return bad


@pytest.mark.parametrize("every", [1, 5, 13])
def test_a_cache_that_accumulates_across_passes_equals_the_live_reader(tmp_path: Path, every: int) -> None:
    assert _steady(tmp_path, every) == []


def test_the_steady_state_scenario_really_differs_from_a_first_sight(tmp_path: Path) -> None:
    lines = write(tmp_path / "f.jsonl", _heal_then_scroll())
    live = str(tmp_path / "live.jsonl")
    reset_history()
    for upto in (25, len(lines)):
        (tmp_path / "live.jsonl").write_bytes(b"".join(r + b"\n" for _rec, r, _e in lines[:upto]))
        steady = read_transcript_facts(live, tail_bytes=TAIL, wide_tail_bytes=1 << 20, now=NOW)
    reset_history()
    first = read_transcript_facts(live, tail_bytes=TAIL, wide_tail_bytes=1 << 20, now=NOW)
    assert steady.mcp_events != first.mcp_events
    assert fold_mcp_health(steady.mcp_events, window_from=steady.mcp_window_from) != fold_mcp_health(
        first.mcp_events, window_from=first.mcp_window_from)


def test_fresh_history_is_a_first_sight_and_the_cache_otherwise_carries_over(tmp_path: Path) -> None:
    case = build(tmp_path, "heal", _heal_then_scroll())
    case.fold(TAIL, 1 << 20)
    first = facts_from_state(case.state, now=NOW, size=case.size, tail_bytes=TAIL, wide_tail_bytes=1 << 20, fresh_history=True)
    assert first.mcp_events == case.legacy(TAIL, 1 << 20).mcp_events
    again = facts_from_state(case.state, now=NOW, size=case.size, tail_bytes=TAIL, wide_tail_bytes=1 << 20)
    assert again.mcp_events == first.mcp_events


def test_a_pass_is_idempotent_and_a_shrunk_file_restarts_the_cache() -> None:
    log = McpLog()
    old = McpEvent(at=None, exact=True, removed=("a",), added=(), failed=(), needs_auth=(), reconnect=False, all_connected=False)
    log.add(10, None, old)
    first = log.joined(0, 100)
    assert log.joined(0, 100) == first and log.history.seen_to == 100
    assert log.joined(0, 50) == first and log.history.seen_to == 50


def test_the_join_rules_are_the_readers_one_copy() -> None:
    entry = HistoryEntry(seen_to=40_000_000)
    assert entry.is_stale(39_999_999) and not entry.is_stale(40_000_000)
    assert entry.scan_start(50_000_000) == 40_000_000 and HistoryEntry().scan_start(10) == 0
    assert join_history((), (), ()) == []


def test_a_whole_file_answer_from_a_bounded_state_refuses(tmp_path: Path) -> None:
    case = build(tmp_path, "bounded", [user(1, "go"), assistant(2, [{"type": "text", "text": "hi"}], stop="end_turn")])
    bounded = ConvState(conv=CONV)
    for record, raw, end in case.lines:
        fold_record(bounded, record, extract_line(ExtractContext(conv=CONV), raw, end), end)
    with pytest.raises(WholeFileUnavailableError):
        facts_from_state(bounded, now=NOW)
    assert facts_from_state(bounded, now=NOW, size=case.size).newest_assistant_at is not None
    assert facts_from_state(bounded, now=NOW, window_start=0).newest_assistant_at is not None
    assert facts_from_state(case.state, now=NOW).newest_assistant_at is not None


def _parity_module() -> Any:
    spec = importlib.util.spec_from_file_location("fold_parity_under_test", PARITY)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(PARITY.parent))
    spec.loader.exec_module(module)
    return module


def test_the_parity_harness_exempts_turn_end_fields_only_where_the_reader_holds_no_turn_end(tmp_path: Path) -> None:
    parity = _parity_module()
    inside = build(tmp_path, "inside", [user(1, "go"), assistant(2, [{"type": "text", "text": "x"}], stop="end_turn"), turn_end(3, pending=2)])
    want = inside.legacy()
    assert want.turn_end_kind is not None and not want.turn_end_outside_window
    assert parity.turn_end_skip(want) == frozenset()
    wrong = parity.dataclasses.replace(inside.fold(), pending_background_agents=3)
    assert "pending_background_agents" in parity.differing_fields(wrong, want, parity.turn_end_skip(want))
    none = build(tmp_path, "none", [user(1, "go"), assistant(2, [{"type": "text", "text": "x"}], stop="end_turn")]).legacy()
    assert none.turn_end_kind is None and parity.turn_end_skip(none) == TURN_END_FIELDS


from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.timeline import fold, mcp_log
from src.core.timeline.facts_adapter import TURN_END_FIELDS, facts_from_state
from src.core.timeline.mcp_log import MAX_EVENTS, McpLog
from src.core.mcp_health.fold import McpEvent
from src.core.timeline.stamps import RecordStarts, SuffixExtreme
from tests.python.timeline.fold_fixtures import (
    NOW,
    TAIL,
    agent_launch,
    assistant,
    build,
    call,
    differences,
    mcp_removed,
    notice,
    shell_launch,
    turn_end,
    user,
    write,
)

RETAIN = 3 * TAIL
CYCLES = 150


def _long_run() -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = [user(1, "go")]
    for i in range(CYCLES):
        base = 10 + i * 10
        records += [assistant(base, [call(f"a{i}", "Agent")], msg=f"a{i}"), agent_launch(base + 1, f"a{i}", f"agent_{i}"),
                    notice(base + 2, f"agent_{i}", f"a{i}"), assistant(base + 3, [call(f"b{i}", "Bash")], msg=f"b{i}"),
                    assistant(base + 4, [call(f"m{i}", "mcp__demo__tool")], msg=f"m{i}"), mcp_removed(base + 5)]
    return records


def test_state_stays_bounded_over_a_long_run_and_a_window_in_retention_still_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fold, "MAX_NOTIFIED", 40)
    monkeypatch.setattr(fold, "MAX_RESULT_IDS", 20)
    monkeypatch.setattr(fold, "TRIM_EVERY", 16)
    monkeypatch.setattr(fold, "MAX_OPEN_CALLS", 10)
    records = _long_run()
    path = tmp_path / "long.jsonl"
    lines = write(path, records)
    state = fold.ConvState(conv="c", retain_bytes=RETAIN)
    for record, _raw, end in lines:
        fold.fold_record(state, record, [], end)
    size = path.stat().st_size
    assert size > 10 * RETAIN
    assert len(state.launches) < 40, "launches behind the retention are dropped"
    assert len(state.notified) <= 40
    assert len(state.result_at) <= 20 and len(state.main_result_at) <= 20
    assert len(state.mcp_open_calls) <= 10 and len(state.mcp_origins) <= 10
    assert len(state.starts) < 2 * (RETAIN + 16 * 400) // 100, "line starts behind the retention are dropped"
    assert len(state.turn_log.ops) < 400
    assert all(len(extreme) < 400 for extreme in state.extremes())
    case = build(tmp_path, "long_case", records)
    bounded = facts_from_state(state, now=NOW, size=size, tail_bytes=TAIL, wide_tail_bytes=TAIL)
    assert differences(bounded, case.legacy(wide=TAIL), TURN_END_FIELDS | {"detail"}) == []


def test_a_zero_turn_end_deletes_the_agent_launches_it_retires(tmp_path: Path) -> None:
    records = [user(1, "go"), assistant(2, [call("t_a", "Agent")]), agent_launch(3, "t_a", "agent_a"), turn_end(4),
               assistant(5, [call("t_s", "Bash")]), shell_launch(6, "t_s", "shell_a"), agent_launch(7, "t_a", "agent_a"),
               assistant(8, [call("t_t", "Bash")]), shell_launch(9, "t_t", "shell_b")]
    case = build(tmp_path, "retire", records)
    assert list(case.state.launches) == ["t_s", "t_a", "t_t"]
    assert differences(case.fold(), case.legacy(), frozenset()) == []
    only_shells = case.legacy()
    assert only_shells.open_background_task_ids == ("shell_a", "shell_b") and only_shells.open_async_agents == 1


def test_the_mcp_log_keeps_the_newest_state_events_and_heals_per_server() -> None:
    log = McpLog()
    for i in range(3000):
        log.add(i * 100, None, McpEvent(at=None, exact=False, removed=(f"s{i}",)))
        log.add(i * 100 + 1, i * 100, McpEvent(at=None, exact=False, reconnect=True, added=("demo",)))
    log.trim(300_000, retain_bytes=300_000)
    states = [r for r in log.recs if r.call is None]
    heals = [r for r in log.recs if r.call is not None]
    assert len(states) == MAX_EVENTS and len(heals) == mcp_log.MAX_HEALS_PER_SERVER
    assert [r.offset for r in log.recs] == sorted(r.offset for r in log.recs)


def test_the_stamp_structures_answer_any_window_start() -> None:
    newest, earliest = SuffixExtreme(True), SuffixExtreme(False)
    base = datetime(2026, 11, 1, tzinfo=timezone.utc)
    stamps = [(0, 5), (100, 50), (200, 9), (300, 1), (400, 7)]
    for offset, second in stamps:
        when = base.replace(second=second)
        newest.observe(when, offset)
        earliest.observe(when, offset)
    for window in (0, 1, 100, 150, 201, 300, 301, 400):
        seen = [s for o, s in stamps if o >= window]
        assert newest.within(window) == (base.replace(second=max(seen)) if seen else None)
        assert earliest.within(window) == (base.replace(second=min(seen)) if seen else None)
    starts = RecordStarts()
    for offset in (0, 100, 250, 900):
        starts.add(offset)
    assert starts.window_start_at(260, 4096) == 250 and starts.window_start_at(100, 4096) == 100
    assert starts.window_start_at(800, 300) == 800, "a line wider than the search leaves the raw offset"
    assert starts.window_start_at(0, 4096) == 0

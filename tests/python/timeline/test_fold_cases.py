
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src.core.attention.transcript_facts import FACTS_FOUND, FACTS_NO_RECORD, FACTS_SHAPE_UNRECOGNIZED
from src.core.attention.transcript_records import TURN_END_INTERRUPT, TURN_END_NO_MODEL_TURN
from src.core.claude_title_sync import read_tail_records
from src.core.timeline.facts_adapter import TURN_END_FIELDS
from tests.python.timeline.fold_fixtures import (
    NO_SKIP,
    TAIL,
    agent_launch,
    assistant,
    at,
    build,
    call,
    differences,
    esc,
    mcp_removed,
    monitor_launch,
    pad,
    quiet_pad,
    result,
    shell_launch,
    stop_result,
    turn_end,
    user,
    workflow_launch,
    fold_lines,
)
from src.core.timeline.fold import ConvState


def _same(tmp_path: Path, name: str, records: List[Dict[str, Any]], skip=NO_SKIP):
    case = build(tmp_path, name, records)
    got, legacy = case.fold(), case.legacy()
    assert differences(got, legacy, skip) == [], name
    return case, got, legacy


def test_timestamps_that_go_backwards_leave_every_newest_field_equal_at_the_window(tmp_path: Path) -> None:
    records = [user(1, "go"), {"type": "queue-operation", "operation": "dequeue", "timestamp": at(10800)}]
    records += [pad(10 + i, i) for i in range(16)]
    records += [assistant(70, [{"type": "text", "text": "x"}], msg="a1", stop="end_turn"),
                {"type": "system", "subtype": "api_request", "timestamp": at(300)},
                assistant(75, [{"type": "text", "text": "y"}], msg="a2", stop="end_turn"),
                user(5, "replayed history"), assistant(6, [{"type": "text", "text": "z"}], msg="a3", stop="end_turn")]
    case, got, legacy = _same(tmp_path, "backwards", records)
    assert read_tail_records(str(case.path), tail_bytes=TAIL).scanned_from > 0
    assert legacy.newest_append_at.isoformat().endswith("10:05:00+00:00")
    assert legacy.mcp_window_from.isoformat().endswith("10:00:05+00:00")


def test_sidechain_records_count_for_the_window_but_not_for_the_leaf(tmp_path: Path) -> None:
    side_call = assistant(40, [call("s_1", "Bash")], msg="s", isSidechain=True)
    side_result = user(41, [{"type": "tool_result", "tool_use_id": "s_1", "content": "ok"}], isSidechain=True)
    records = [user(1, "go"), assistant(2, [call("t_a", "Agent")]), agent_launch(3, "t_a", "agent_a"),
               *[pad(10 + i, i) for i in range(16)], side_call, side_result,
               assistant(50, [call("s_2", "Bash")], msg="s2", isSidechain=True)]
    case, got, legacy = _same(tmp_path, "sidechain", records)
    assert legacy.newest_assistant_at is not None and legacy.blocked_on_tool is None
    assert "unanswered call to Bash" in legacy.detail


def test_a_compaction_window_of_only_bookkeeping_is_read_again_wide(tmp_path: Path) -> None:
    records = [user(1, "go"), assistant(2, [call("t_a", "Agent")]), agent_launch(3, "t_a", "agent_old"),
               turn_end(4, pending=1), {"type": "system", "subtype": "compact_boundary", "timestamp": at(5)},
               *[quiet_pad(10 + i) for i in range(30)]]
    case, got, legacy = _same(tmp_path, "compaction", records)
    narrow = case.legacy(wide=TAIL)
    assert narrow.verdict == FACTS_NO_RECORD and narrow.turn_end_outside_window
    assert legacy.verdict == FACTS_FOUND and legacy.pending_background_agents == 1 and legacy.open_async_agents == 1


def test_a_workflow_launch_is_counted_apart_and_a_zero_turn_end_does_not_retire_it(tmp_path: Path) -> None:
    records = [user(1, "go"), assistant(2, [call("t_w", "Workflow")]), workflow_launch(3, "t_w", "wf_1"),
               turn_end(4, pending=0, pendingWorkflowCount=1)]
    _case, _got, legacy = _same(tmp_path, "workflow", records)
    assert (legacy.open_async_agents, legacy.open_workflows, legacy.pending_workflows) == (1, 1, 1)


def test_a_monitor_survives_a_zero_turn_end_and_a_stop_closes_it(tmp_path: Path) -> None:
    base = [user(1, "go"), assistant(2, [call("t_m", "Monitor")]), monitor_launch(3, "t_m", "mon_1"),
            assistant(4, [call("t_k", "Bash")]), shell_launch(5, "t_k", "sh_1"), turn_end(6)]
    _case, _got, open_ = _same(tmp_path, "monitor", base)
    assert open_.open_background_tasks == 2
    stopped = base + [assistant(7, [call("t_s", "TaskStop")]), stop_result(8, "t_s", "sh_1")]
    _case, _got, after = _same(tmp_path, "stopped", stopped)
    assert after.open_background_tasks == 1 and after.open_background_task_ids == ("mon_1",)


def test_a_resume_placeholder_is_not_model_output(tmp_path: Path) -> None:
    placeholder = {"type": "assistant", "timestamp": at(9), "message": {
        "id": "ph", "model": "<synthetic>", "stop_reason": "stop_sequence",
        "content": [{"type": "text", "text": "No response requested."}]}}
    records = [user(1, "go"), assistant(2, [{"type": "text", "text": "x"}], msg="a1", stop="end_turn"), placeholder]
    _case, _got, legacy = _same(tmp_path, "placeholder", records)
    assert legacy.newest_assistant_at.isoformat().endswith("10:00:02+00:00") and legacy.verdict == FACTS_NO_RECORD


def test_a_file_of_only_local_commands_has_no_model_turn(tmp_path: Path) -> None:
    records = [user(1, "<command-name>/mcp</command-name>"),
               user(2, "<local-command-stdout>Reconnected to demo.</local-command-stdout>")]
    _case, _got, legacy = _same(tmp_path, "local_only", records)
    assert legacy.turn_end_kind == TURN_END_NO_MODEL_TURN and legacy.pending_background_agents == 0


def test_esc_over_an_unanswered_tool_is_not_a_turn_end_and_over_an_answered_one_is(tmp_path: Path) -> None:
    unanswered = [user(1, "go"), assistant(2, [call("t_a", "Bash")]), esc(3, tool=True)]
    _case, _got, legacy = _same(tmp_path, "esc_open", unanswered)
    assert legacy.turn_end_kind is None
    answered = [user(1, "go"), assistant(2, [call("t_a", "Bash")]), result(3, "t_a"), esc(4)]
    _case, _got, legacy = _same(tmp_path, "esc_done", answered)
    assert legacy.turn_end_kind == TURN_END_INTERRUPT and legacy.pending_background_agents == 0


def test_a_second_mcp_call_and_a_call_from_before_the_window_join_like_the_legacy_history(tmp_path: Path) -> None:
    records = [mcp_removed(1), user(2, "go"), assistant(3, [call("m_1", "mcp__demo__first")]),
               *[pad(10 + i, i) for i in range(16)], result(60, "m_1"),
               assistant(61, [call("m_2", "mcp__demo__second")]), result(62, "m_2"),
               assistant(63, [call("m_3", "mcp__demo__third")]), result(64, "m_3")]
    case, got, legacy = _same(tmp_path, "mcp_calls", records)
    assert read_tail_records(str(case.path), tail_bytes=TAIL).scanned_from > 0
    heals = [e for e in legacy.mcp_events if e.reconnect and not e.exact]
    assert len(heals) == 1 and heals[0].at.isoformat().endswith("10:01:04+00:00")


MID = 16384


def _wide_records() -> List[Dict[str, Any]]:
    return [*[pad(1 + i, 100 + i) for i in range(10)],
            user(20, "go"), assistant(21, [call("t_a", "Agent")]), agent_launch(22, "t_a", "agent_far"), turn_end(23, pending=1),
            *[pad(30 + i, i) for i in range(20)],
            user(60, "again"), assistant(61, [call("t_b", "Bash")]), result(62, "t_b"), esc(63)]


def test_the_wide_reread_takes_every_field_from_the_wider_window(tmp_path: Path) -> None:
    case, got, legacy = _same(tmp_path, "wide", _wide_records())
    assert legacy.open_async_agents == 1 and legacy.pending_background_agents == 1 and legacy.turn_end_kind == TURN_END_INTERRUPT
    far = TAIL * 2
    assert differences(case.fold(wide=far), case.legacy(wide=far), TURN_END_FIELDS) == []
    missed = case.legacy(wide=far)
    assert missed.pending_background_agents is None and missed.turn_end_outside_window and missed.open_async_agents == 0


def test_a_state_seeded_from_a_window_answers_as_the_reader_does(tmp_path: Path) -> None:
    case = build(tmp_path, "seeded", _wide_records())
    narrow_from = read_tail_records(str(case.path), tail_bytes=TAIL).scanned_from
    wide_from = read_tail_records(str(case.path), tail_bytes=MID).scanned_from
    assert 0 < wide_from < narrow_from

    def starting_at(first_byte: int) -> ConvState:
        index = next(i for i, line in enumerate(case.lines) if line[2] - len(line[1]) - 1 >= first_byte)
        return fold_lines(case.lines, from_line=index)

    seeded = starting_at(narrow_from)
    assert seeded.coverage_start == narrow_from and not seeded.whole
    assert differences(case.fold(wide=TAIL, state=seeded), case.legacy(wide=TAIL), TURN_END_FIELDS) == []
    seeded_wide = starting_at(wide_from)
    assert seeded_wide.coverage_start == wide_from
    assert differences(case.fold(wide=MID, state=seeded_wide), case.legacy(wide=MID), NO_SKIP) == []


def test_a_line_that_breaks_the_shape_contract_inside_the_window_names_it_and_blanks_the_counts(tmp_path: Path) -> None:
    broken = {"type": "user", "timestamp": at(3)}
    inside = [user(1, "go"), turn_end(2, pending=1), *[pad(10 + i, i) for i in range(16)], broken,
              assistant(70, [{"type": "text", "text": "x"}], msg="a", stop="end_turn"), turn_end(71, pending=2)]
    _case, got, legacy = _same(tmp_path, "contract_in", inside)
    assert legacy.verdict == FACTS_SHAPE_UNRECOGNIZED and legacy.pending_background_agents is None and legacy.shape_problems
    before = [broken, user(1, "go"), *[pad(10 + i, i) for i in range(16)], turn_end(71, pending=2)]
    _case, got, legacy = _same(tmp_path, "contract_out", before)
    assert legacy.verdict == FACTS_FOUND and legacy.pending_background_agents == 2 and not legacy.shape_problems

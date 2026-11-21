
from __future__ import annotations

from pathlib import Path

from tests.python.timeline.fold_fixtures import (
    agent_launch, assistant, build, call, differences, NO_SKIP, notice, pad, result, user,
)


def test_a_call_answered_before_its_replayed_copy_is_still_answered_for_the_toast(tmp_path: Path) -> None:
    case = build(tmp_path, "replayed_call", [user(1, "go"), assistant(2, [call("t_x", "Agent")], msg="m1"), result(3, "t_x"),
                                              assistant(4, [call("t_x", "Agent")], msg="m1")])
    legacy = case.legacy()
    assert legacy.toast_facts.pending_tool is None
    assert differences(case.fold(), legacy, NO_SKIP) == []


def test_a_notice_from_before_the_window_does_not_complete_a_launch_replayed_inside_it(tmp_path: Path) -> None:
    records = [user(1, "go"), assistant(2, [call("t_a", "Agent")]), agent_launch(3, "t_a", "agent_1"), notice(4, "agent_1", "t_a")]
    records += [pad(10 + i, i) for i in range(16)]
    records += [agent_launch(60, "t_a", "agent_1")]
    case = build(tmp_path, "replayed_launch", records)
    legacy = case.legacy()
    assert legacy.open_async_agents == 1
    assert differences(case.fold(), legacy, NO_SKIP) == []


def test_a_blocking_call_answered_before_the_window_is_blocked_again_when_replayed_inside_it(tmp_path: Path) -> None:
    records = [user(1, "go"), assistant(2, [call("t_q", "AskUserQuestion")], msg="m1"), result(3, "t_q")]
    records += [pad(10 + i, i) for i in range(16)]
    records += [assistant(60, [call("t_q", "AskUserQuestion")], msg="m1")]
    case = build(tmp_path, "replayed_blocking", records)
    legacy = case.legacy()
    assert legacy.blocked_on_tool == "AskUserQuestion"
    assert differences(case.fold(), legacy, NO_SKIP) == []

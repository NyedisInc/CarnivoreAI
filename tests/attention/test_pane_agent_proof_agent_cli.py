
from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

import pytest

from src.core.attention.pane_agent_proof import registered_agent_in_foreground
from src.core.session_one_shot_gate import OneShotRefused, check_can_paste

PANE, SHELL, AGY, FLOOR = 7349, 7349, 7936, 1_800_000_000


def _lstart(epoch: int) -> str:
    return time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(epoch))


def _proof(agent_type: Optional[str], *, command: str = "/usr/local/bin/agy --model x",
           groups: Optional[Tuple[int, int]] = (PANE, PANE), started: Optional[int] = FLOOR + 5,
           floor: Optional[int] = FLOOR, parents: Optional[Dict[int, int]] = None) -> bool:
    table = {SHELL: "zsh -c source wrapper.zsh", AGY: command}
    return registered_agent_in_foreground(
        tmux_name="carnivore_x", pane_id="%5", pane_pid=PANE, session_started_epoch=floor, index={},
        parents=lambda: parents if parents is not None else {SHELL: 1, AGY: SHELL},
        commands=lambda: table, foreground=lambda pid: groups,
        starts=lambda pids: {} if started is None else {AGY: _lstart(started)},
        agent_type=agent_type,
    )


def _gate(proven: bool, agent_type: str = "antigravity") -> None:
    check_can_paste(pane_current_command="zsh", pane_dead="0", agent_type=agent_type,
                    activity_status="idle", startup_gate="ready", foreground_agent_proven=proven)


def test_agy_in_the_foreground_under_zsh_proves_an_antigravity_row() -> None:
    assert _proof("antigravity") is True
    assert _proof("agy") is True
    _gate(True)


def test_the_same_process_does_not_prove_a_claude_row() -> None:
    assert _proof("claude") is False
    assert _proof(None) is False


def test_a_bare_shell_in_the_foreground_proves_nothing() -> None:
    assert _proof("antigravity", command="zsh -c sleep 600") is False
    with pytest.raises(OneShotRefused):
        _gate(False)


def test_a_foreground_group_that_is_not_the_terminals_refuses() -> None:
    assert _proof("antigravity", groups=(AGY, PANE)) is False


@pytest.mark.parametrize("groups,started,floor", [
    (None, FLOOR + 5, FLOOR),
    ((PANE, PANE), None, FLOOR),
    ((PANE, PANE), FLOOR + 5, None),
    ((PANE, 0), FLOOR + 5, FLOOR),
])
def test_an_unread_fact_refuses(groups, started, floor) -> None:
    assert _proof("antigravity", groups=groups, started=started, floor=floor) is False


def test_an_agy_started_before_the_instance_floor_refuses() -> None:
    assert _proof("antigravity", started=FLOOR - 60) is False


def test_an_agy_that_does_not_descend_from_the_pane_refuses() -> None:
    assert _proof("antigravity", parents={SHELL: 1, AGY: 1}) is False


def test_a_renamed_agy_profile_is_proven_by_its_agent_block_not_its_id(monkeypatch) -> None:
    from src.config import settings

    with_block = {"id": "agy-work", "agent": {"process": "agy", "rules": "agy"}}
    monkeypatch.setattr(type(settings), "get_launch_profiles", lambda self: [with_block])
    assert _proof("agy-work") is True
    monkeypatch.setattr(type(settings), "get_launch_profiles", lambda self: [{"id": "agy-work"}])
    assert _proof("agy-work") is False


def test_a_profile_whose_agent_block_names_a_shell_never_proves_a_bare_shell(monkeypatch) -> None:
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_launch_profiles", lambda self: [{"id": "myagent", "agent": {"process": "zsh"}}])
    proven = registered_agent_in_foreground(
        tmux_name="carnivore_x", pane_id="%5", pane_pid=PANE, session_started_epoch=FLOOR, index={},
        parents=lambda: {SHELL: 1}, commands=lambda: {SHELL: "zsh"}, foreground=lambda pid: (PANE, PANE),
        starts=lambda pids: {SHELL: _lstart(FLOOR + 1)}, agent_type="myagent",
    )
    assert proven is False

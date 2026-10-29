
from __future__ import annotations

import pytest

from src.core.session_respawn import (
    ACTIONABLE_RESPAWN_KINDS,
    ALL_RESPAWN_KINDS,
    RESPAWN_AGENT,
    RESPAWN_CANNOT_DETERMINE,
    RESPAWN_NOT_DEAD,
    RESPAWN_REPLAY,
    RESPAWN_SHELL,
    RespawnPlan,
    resolve_respawn_plan,
)


def test_dead_pane_with_agent_record_re_derives_the_agent_command():
    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead="1",
        pane_start_command='"cld"',
        agent_command="zsh -c 'source ~/.zshrc; cld'",
    )
    assert plan.kind == RESPAWN_AGENT
    assert plan.command == "zsh -c 'source ~/.zshrc; cld'"
    assert plan.actionable is True


def test_re_derived_command_wins_over_the_stale_recorded_one():
    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead="1",
        pane_start_command='"/old/path/claude --flag"',
        agent_command="/new/path/claude --flag",
    )
    assert plan.command == "/new/path/claude --flag"
    assert "/old/path" not in (plan.command or "")


def test_dead_pane_without_agent_record_replays_tmux_own_command():
    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead="1",
        pane_start_command='"codex"',
        agent_command=None,
    )
    assert plan.kind == RESPAWN_REPLAY
    assert plan.command is None
    assert plan.actionable is True


@pytest.mark.parametrize("agent_command", ["cld", "claude --dangerously-skip-permissions"])
def test_bare_shell_pane_never_launches_an_agent(agent_command):
    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead="1",
        pane_start_command="",
        agent_command=agent_command,
    )
    assert plan.kind == RESPAWN_SHELL
    assert plan.command is None
    assert plan.actionable is True


def test_failed_probe_is_cannot_determine_not_a_guess():
    plan = resolve_respawn_plan(
        probe_ok=False,
        pane_dead=None,
        pane_start_command=None,
        agent_command="cld",
    )
    assert plan.kind == RESPAWN_CANNOT_DETERMINE
    assert plan.command is None
    assert plan.actionable is False
    assert "cannot be determined" in plan.detail


def test_missing_start_command_field_is_cannot_determine():
    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead="1",
        pane_start_command=None,
        agent_command="cld",
    )
    assert plan.kind == RESPAWN_CANNOT_DETERMINE
    assert plan.actionable is False


def test_live_pane_is_not_dead_and_is_not_actionable():
    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead="0",
        pane_start_command='"cld"',
        agent_command="cld",
    )
    assert plan.kind == RESPAWN_NOT_DEAD
    assert plan.actionable is False
    assert plan.command is None


def test_every_kind_carries_a_sentence_the_ui_can_show():
    cases = [
        dict(probe_ok=True, pane_dead="1", pane_start_command='"cld"', agent_command="cld"),
        dict(probe_ok=True, pane_dead="1", pane_start_command='"x"', agent_command=None),
        dict(probe_ok=True, pane_dead="1", pane_start_command="", agent_command=None),
        dict(probe_ok=True, pane_dead="0", pane_start_command="", agent_command=None),
        dict(probe_ok=False, pane_dead=None, pane_start_command=None, agent_command=None),
    ]
    seen = set()
    for kw in cases:
        plan = resolve_respawn_plan(**kw)
        seen.add(plan.kind)
        assert plan.detail.strip(), f"{plan.kind} has no detail sentence"

    from src.core.session_respawn import (
        RESPAWN_REPLAY,
        refuse_if_transcript_missing,
    )

    replayed = RespawnPlan(
        kind=RESPAWN_REPLAY,
        detail="restarting the command tmux recorded for this pane",
        resume_uuid="82aabe7b-c0be-4430-b127-bbf8aad17a57",
    )
    refused = refuse_if_transcript_missing(replayed, "absent")
    seen.add(refused.kind)
    assert refused.detail.strip(), "transcript_missing has no detail sentence"

    assert seen == ALL_RESPAWN_KINDS


def test_non_actionable_kinds_never_carry_a_command():
    for kind in ALL_RESPAWN_KINDS - ACTIONABLE_RESPAWN_KINDS:
        assert kind not in ACTIONABLE_RESPAWN_KINDS
    assert RespawnPlan(kind=RESPAWN_CANNOT_DETERMINE).command is None
    assert RespawnPlan(kind=RESPAWN_NOT_DEAD).command is None


def test_whitespace_only_agent_command_falls_through_to_replay():
    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead="1",
        pane_start_command='"cld"',
        agent_command="   ",
    )
    assert plan.kind == RESPAWN_REPLAY

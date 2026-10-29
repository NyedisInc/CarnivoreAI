
from __future__ import annotations

from src.config.agent_command import agent_command
from src.config.agents import AgentsConfig
from src.core.agent_wrappers import AgentWrapper
from src.core.session_resume_target import (
    CONVERSATION_RESUMED,
    ResumeTarget,
    resume_extra_args,
    resume_target_from_row,
)

UUID = "ad166ca4-f8b4-989f-dee8-b5b4f34999e3"


def test_claude_resume_is_the_dash_dash_resume_flag():
    target = ResumeTarget(
        outcome=CONVERSATION_RESUMED, claude_session_uuid=UUID, family="claude"
    )
    assert resume_extra_args(target) == ["--resume", UUID]


def test_codex_resume_is_the_resume_subcommand_not_a_flag():
    target = ResumeTarget(
        outcome=CONVERSATION_RESUMED, claude_session_uuid=UUID, family="codex"
    )
    args = resume_extra_args(target)
    assert args == ["resume", UUID]
    assert "--resume" not in args


def test_a_row_without_a_family_defaults_to_the_claude_flag():
    target = ResumeTarget(outcome=CONVERSATION_RESUMED, claude_session_uuid=UUID)
    assert resume_extra_args(target) == ["--resume", UUID]


def test_resume_target_from_row_carries_the_family():
    row = {"claude_session_uuid": UUID, "agent_family": "codex"}
    target = resume_target_from_row(row, row_read_ok=True)
    assert target.family == "codex"
    assert target.claude_session_uuid == UUID


def test_codex_launch_disables_alt_screen_with_and_without_a_configured_wrapper(tmp_path):
    def launch(agents, enabled):
        return agent_command(
            "codex", agents=agents,
            resolve_state_dir=lambda: str(tmp_path),
            disable_alternate_screen=lambda: enabled,
            extra_args=["resume", UUID],
        )

    standard = AgentsConfig(wrappers=[])
    command = launch(standard, True)
    assert command.endswith("_ resume %s --no-alt-screen" % UUID)
    assert "--no-alt-screen" not in launch(standard, False)

    wrapper = AgentWrapper(id="cx", family="codex", label="codex", script='codex "$@"')
    wrapped = launch(AgentsConfig(wrappers=[wrapper]), True)
    assert "--no-alt-screen" in wrapped
    assert "--no-alt-screen" not in launch(AgentsConfig(wrappers=[wrapper]), False)




def _adopted_codex_row():
    return {"claude_session_uuid": "", "agent_family": "codex"}


def _exploding_pick(_working_dir):
    raise AssertionError("the restart-time pick must not run for this row")


def test_adopted_codex_empty_column_resumes_on_the_live_pick():
    from src.core.session_resume_target import upgrade_codex_adopted_target

    picked = "ad166ca4-f8b4-989f-dee8-b5b4f34999e3"
    base = resume_target_from_row(_adopted_codex_row(), row_read_ok=True)
    assert resume_extra_args(base) is None

    upgraded = upgrade_codex_adopted_target(
        base, working_dir="/p", pick=lambda wd: picked
    )
    assert upgraded.outcome == CONVERSATION_RESUMED
    assert upgraded.family == "codex"
    args = resume_extra_args(upgraded)
    assert args == ["resume", picked]
    assert "--resume" not in args


def test_adopted_codex_ambiguous_pick_resumes_fresh_no_uuid():
    from src.core.session_resume_target import (
        CONVERSATION_NONE_RECORDED,
        upgrade_codex_adopted_target,
    )

    base = resume_target_from_row(_adopted_codex_row(), row_read_ok=True)
    upgraded = upgrade_codex_adopted_target(
        base, working_dir="/p", pick=lambda wd: None
    )
    assert upgraded.outcome == CONVERSATION_NONE_RECORDED
    assert upgraded.claude_session_uuid is None
    assert resume_extra_args(upgraded) is None


def test_adopted_codex_with_no_working_dir_never_picks():
    from src.core.session_resume_target import (
        CONVERSATION_NONE_RECORDED,
        upgrade_codex_adopted_target,
    )

    base = resume_target_from_row(_adopted_codex_row(), row_read_ok=True)
    upgraded = upgrade_codex_adopted_target(
        base, working_dir=None, pick=_exploding_pick
    )
    assert upgraded.outcome == CONVERSATION_NONE_RECORDED
    assert resume_extra_args(upgraded) is None


def test_created_codex_with_bound_uuid_is_never_repicked():
    from src.core.session_resume_target import upgrade_codex_adopted_target

    row = {"claude_session_uuid": UUID, "agent_family": "codex"}
    base = resume_target_from_row(row, row_read_ok=True)
    assert base.outcome == CONVERSATION_RESUMED
    upgraded = upgrade_codex_adopted_target(
        base, working_dir="/p", pick=_exploding_pick
    )
    assert resume_extra_args(upgraded) == ["resume", UUID]


def test_claude_adopted_row_is_untouched_by_the_codex_pick():
    from src.core.session_resume_target import upgrade_codex_adopted_target

    row = {"claude_session_uuid": UUID, "agent_family": "claude"}
    base = resume_target_from_row(row, row_read_ok=True)
    upgraded = upgrade_codex_adopted_target(
        base, working_dir="/p", pick=_exploding_pick
    )
    assert resume_extra_args(upgraded) == ["--resume", UUID]


def test_claude_adopted_empty_column_is_untouched_by_the_codex_pick():
    from src.core.session_resume_target import (
        CONVERSATION_NONE_RECORDED,
        upgrade_codex_adopted_target,
    )

    row = {"claude_session_uuid": "", "agent_family": "claude"}
    base = resume_target_from_row(row, row_read_ok=True)
    upgraded = upgrade_codex_adopted_target(
        base, working_dir="/p", pick=_exploding_pick
    )
    assert upgraded.outcome == CONVERSATION_NONE_RECORDED
    assert resume_extra_args(upgraded) is None


def test_unknown_family_adopted_row_degrades_with_no_flag():
    from src.core.session_resume_target import (
        CONVERSATION_NONE_RECORDED,
        upgrade_codex_adopted_target,
    )

    row = {"claude_session_uuid": "", "agent_family": "gemini"}
    base = resume_target_from_row(row, row_read_ok=True)
    upgraded = upgrade_codex_adopted_target(
        base, working_dir="/p", pick=_exploding_pick
    )
    assert upgraded.outcome == CONVERSATION_NONE_RECORDED
    args = resume_extra_args(upgraded)
    assert args is None
    assert args != ["--resume", ""]

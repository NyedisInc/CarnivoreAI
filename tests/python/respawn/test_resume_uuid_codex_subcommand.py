
from __future__ import annotations

from src.core.session_respawn import (
    RESPAWN_AGENT,
    RESPAWN_TRANSCRIPT_MISSING,
    project_restart_rung,
    refuse_if_transcript_missing,
    resume_uuid_in,
)
from src.core.session_resume_target import (
    CONVERSATION_RESUMED,
    CONVERSATION_UNKNOWN,
)

UUID = "82aabe7b-c0be-4430-b127-bbf8aad17a57"


def test_resume_uuid_in_reads_the_codex_subcommand_form():
    command = (
        "zsh -c 'source ~/.zshrc >/dev/null 2>&1; exec codex resume "
        f"{UUID} --yolo'"
    )
    assert resume_uuid_in(command) == UUID


def test_resume_uuid_in_still_reads_the_claude_flag_form():
    command = f"zsh -c 'source ~/.zshrc >/dev/null 2>&1; exec claude --resume {UUID}'"
    assert resume_uuid_in(command) == UUID


def test_codex_restart_plan_reports_resumed_from_the_command_itself():
    command = f"zsh -c 'source ~/.zshrc; exec codex resume {UUID} --yolo'"
    plan = project_restart_rung(
        probe_ok=True,
        pane_start_command='"cld"',
        agent_command=command,
        resume_outcome=None,
    )
    assert plan.kind == RESPAWN_AGENT
    assert plan.resume_uuid == UUID
    assert plan.conversation == CONVERSATION_RESUMED


def test_claude_restart_plan_is_unchanged():
    command = f"zsh -c 'source ~/.zshrc; exec claude --resume {UUID}'"
    plan = project_restart_rung(
        probe_ok=True,
        pane_start_command='"cld"',
        agent_command=command,
        resume_outcome=None,
    )
    assert plan.kind == RESPAWN_AGENT
    assert plan.resume_uuid == UUID
    assert plan.conversation == CONVERSATION_RESUMED


def test_codex_restart_now_runs_the_transcript_check():
    command = f"zsh -c 'source ~/.zshrc; exec codex resume {UUID} --yolo'"
    plan = project_restart_rung(
        probe_ok=True,
        pane_start_command='"cld"',
        agent_command=command,
        resume_outcome=None,
    )
    refused = refuse_if_transcript_missing(plan, "absent")
    assert refused.kind == RESPAWN_TRANSCRIPT_MISSING
    assert refused.conversation == CONVERSATION_UNKNOWN

    untouched = refuse_if_transcript_missing(plan, "present")
    assert untouched.kind == RESPAWN_AGENT
    untouched_unchecked = refuse_if_transcript_missing(plan, "unchecked")
    assert untouched_unchecked.kind == RESPAWN_AGENT

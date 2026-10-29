
from __future__ import annotations

from src.core.session_resume_target import (
    CONVERSATION_NONE_RECORDED,
    CONVERSATION_RESUMED,
    CONVERSATION_UNKNOWN,
    ResumeTarget,
    resume_extra_args,
    resume_target_from_row,
)


def test_resume_target_from_row_reads_title():
    target = resume_target_from_row(
        {"claude_session_uuid": "u1", "title": "Spike"}, row_read_ok=True
    )
    assert target.outcome == CONVERSATION_RESUMED
    assert target.title == "Spike"


def test_resume_target_from_row_title_absent():
    target = resume_target_from_row(
        {"claude_session_uuid": "u1", "title": ""}, row_read_ok=True
    )
    assert target.title is None


def test_resume_target_from_row_carries_title_on_none_recorded():
    target = resume_target_from_row(
        {"claude_session_uuid": None, "title": "Spike"}, row_read_ok=True
    )
    assert target.outcome == CONVERSATION_NONE_RECORDED
    assert target.title == "Spike"


def test_resume_extra_args_appends_name_for_claude():
    target = ResumeTarget(CONVERSATION_RESUMED, "u1", title="Spike")
    assert resume_extra_args(target) == ["--resume", "u1", "--name", "Spike"]


def test_resume_extra_args_no_title_adds_nothing():
    target = ResumeTarget(CONVERSATION_RESUMED, "u1")
    assert resume_extra_args(target) == ["--resume", "u1"]


def test_resume_extra_args_unpushable_title_adds_nothing():
    target = ResumeTarget(CONVERSATION_RESUMED, "u1", title="line1\nline2")
    assert resume_extra_args(target) == ["--resume", "u1"]


def test_resume_extra_args_never_adds_name_for_codex():
    target = ResumeTarget(
        CONVERSATION_RESUMED, "u1", family="codex", title="Spike"
    )
    assert resume_extra_args(target) == ["resume", "u1"]


def test_resume_extra_args_none_outcome_still_returns_none():
    target = ResumeTarget(CONVERSATION_NONE_RECORDED, title="Spike")
    assert resume_extra_args(target) is None


def test_resume_extra_args_unknown_outcome_returns_none():
    target = ResumeTarget(CONVERSATION_UNKNOWN, title="Spike")
    assert resume_extra_args(target) is None

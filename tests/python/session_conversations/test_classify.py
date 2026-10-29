
from __future__ import annotations

import pytest

from src.core.session_conversations import classify
from src.core.session_conversations import constants as K

from .helpers import A_ID, command_lines, fork_lines, normal_lines, user, write_transcript


@pytest.mark.parametrize("command,expected", [("/clear", "clear"), ("/reset", "reset"), ("/new", "new")])
def test_a_clear_family_command_names_the_reason(tmp_path, command, expected):
    path = write_transcript(tmp_path, "b", command_lines(command, prompt="start fresh"))
    head = classify.read_head(path)
    assert head.command == command and head.first_prompt == "start fresh"
    assert classify.ended_reason(head, A_ID) == expected


def test_a_forked_from_pointer_is_a_fork_never_a_clear(tmp_path):
    head = classify.read_head(write_transcript(tmp_path, "b", fork_lines(A_ID)))
    assert head.forked_from == A_ID and classify.ended_reason(head, A_ID) == K.ENDED_FORK


def test_an_ordinary_start_is_switch_not_a_guess(tmp_path):
    head = classify.read_head(write_transcript(tmp_path, "b", normal_lines()))
    assert head.command is None and classify.ended_reason(head, A_ID) == K.ENDED_SWITCH


def test_a_clear_typed_later_is_not_how_the_conversation_began(tmp_path):
    lines = normal_lines() + command_lines("/clear")
    head = classify.read_head(write_transcript(tmp_path, "b", lines))
    assert head.command is None and classify.ended_reason(head, A_ID) == K.ENDED_SWITCH


def test_a_non_clear_command_is_switch(tmp_path):
    lines = [user("<command-name>/model</command-name><command-message>model</command-message>", "2026-09-02T09:00:00Z"),
             user("go", "2026-09-02T09:00:01Z")]
    head = classify.read_head(write_transcript(tmp_path, "b", lines))
    assert head.command == "/model" and classify.ended_reason(head, A_ID) == K.ENDED_SWITCH


def test_an_unreadable_transcript_is_switch_and_never_raises(tmp_path):
    head = classify.read_head(tmp_path / "missing.jsonl")
    assert head == classify.Head() and classify.ended_reason(head, A_ID) == K.ENDED_SWITCH


def test_only_a_bounded_head_is_read(tmp_path):
    lines = normal_lines(prompt="x" * 200) + [user("y" * 500, "2026-09-01T11:00:00Z") for _ in range(400)]
    path = write_transcript(tmp_path, "b", lines)
    head = classify.read_head(path, max_bytes=2048, max_records=3)
    assert head.first_prompt.startswith("x") and head.started_at == "2026-09-01T10:00:00Z"

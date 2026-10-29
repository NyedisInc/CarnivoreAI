
from __future__ import annotations

import pytest

from src.core.session_kind import (
    KIND_AUTOMATED,
    KIND_INTERACTIVE,
    KIND_UNKNOWN,
    MARKER_HEADLESS_ENTRYPOINT,
    MARKER_INTERACTIVE_ENTRYPOINT,
    MARKER_NONE,
    MARKER_PLAN_APPROVED,
    MARKER_SCHEDULER_TAG,
    MARKER_TUI_RECORD,
    MARKER_UNREADABLE,
    SESSION_KINDS,
    classify_records,
    classify_transcript,
)


SCHEDULER_ENQUEUE = {
    "type": "queue-operation",
    "operation": "enqueue",
    "sessionId": "94d7ab22-f546-46a6-9e1c-0002ca583503",
    "content": (
        '<scheduled-task name="hirsch-9pm-reboots" '
        'file="/Users/x/.claude/scheduled-tasks/hirsch-9pm-reboots/SKILL.md">\n'
    ),
}

SCHEDULER_USER = {
    "type": "user",
    "userType": "external",
    "entrypoint": "claude-desktop",
    "promptSource": "sdk",
    "permissionMode": "default",
    "isSidechain": False,
}

HEADLESS_USER = {
    "type": "user",
    "userType": "external",
    "entrypoint": "sdk-cli",
    "promptSource": "sdk",
    "permissionMode": "bypassPermissions",
    "isSidechain": False,
}

TUI_USER = {
    "type": "user",
    "userType": "external",
    "entrypoint": "cli",
    "permissionMode": "bypassPermissions",
    "isSidechain": False,
}

DESKTOP_USER = dict(TUI_USER, entrypoint="claude-desktop")

PLAN_USER = {
    "type": "user",
    "userType": "external",
    "cwd": "/Users/x/Development/Web/eastern",
    "isSidechain": False,
    "planContent": "# Unified Data Grid System\n\n1. ...",
}

OLD_USER = {
    "type": "user",
    "userType": "external",
    "cwd": "/Users/x/Development/CloudeCode",
    "sessionId": "0f0f",
    "version": "2.1.39",
    "isSidechain": False,
    "permissionMode": "default",
}

CUSTOM_TITLE = {
    "type": "custom-title",
    "customTitle": "Agent - Infrastructure (HA)",
    "sessionId": "1f48367b",
}




def test_scheduler_tag_is_automated():
    verdict = classify_records([SCHEDULER_ENQUEUE, SCHEDULER_USER])
    assert verdict.kind == KIND_AUTOMATED
    assert verdict.marker == MARKER_SCHEDULER_TAG


def test_scheduler_tag_outranks_the_interactive_entrypoint():
    verdict = classify_records([SCHEDULER_ENQUEUE, SCHEDULER_USER, CUSTOM_TITLE])
    assert verdict.kind == KIND_AUTOMATED


def test_scheduler_tag_is_read_from_a_user_message_too():
    user = dict(
        SCHEDULER_USER,
        message={"role": "user", "content": '<scheduled-task name="x"/>'},
    )
    assert classify_records([user]).kind == KIND_AUTOMATED


def test_headless_sdk_entrypoint_is_automated():
    verdict = classify_records([HEADLESS_USER])
    assert verdict.kind == KIND_AUTOMATED
    assert verdict.marker == MARKER_HEADLESS_ENTRYPOINT




@pytest.mark.parametrize("record", [TUI_USER, DESKTOP_USER])
def test_human_entrypoints_are_interactive(record):
    verdict = classify_records([record])
    assert verdict.kind == KIND_INTERACTIVE
    assert verdict.marker == MARKER_INTERACTIVE_ENTRYPOINT


def test_plan_content_is_interactive():
    verdict = classify_records([PLAN_USER])
    assert verdict.kind == KIND_INTERACTIVE
    assert verdict.marker == MARKER_PLAN_APPROVED


def test_custom_title_record_is_interactive():
    verdict = classify_records([OLD_USER, CUSTOM_TITLE])
    assert verdict.kind == KIND_INTERACTIVE
    assert verdict.marker == MARKER_TUI_RECORD


def test_mixed_entrypoints_keep_the_row():
    verdict = classify_records([HEADLESS_USER, TUI_USER])
    assert verdict.kind == KIND_INTERACTIVE




def test_a_transcript_with_no_markers_is_unknown_not_automated():
    verdict = classify_records([OLD_USER, dict(OLD_USER, type="assistant")])
    assert verdict.kind == KIND_UNKNOWN
    assert verdict.marker == MARKER_NONE


def test_an_empty_transcript_is_unknown():
    assert classify_records([]).kind == KIND_UNKNOWN


def test_a_non_dict_record_does_not_raise():
    assert classify_records([None, 3, "x", OLD_USER]).kind == KIND_UNKNOWN


def test_an_unreadable_file_is_unknown_with_its_own_marker(tmp_path):
    verdict = classify_transcript(str(tmp_path / "absent.jsonl"))
    assert verdict.kind == KIND_UNKNOWN
    assert verdict.marker == MARKER_UNREADABLE


def test_a_malformed_line_is_skipped_not_fatal(tmp_path):
    import json

    path = tmp_path / "t.jsonl"
    path.write_text(
        json.dumps(SCHEDULER_ENQUEUE) + "\n{ this is not json\n\n"
    )
    assert classify_transcript(str(path)).kind == KIND_AUTOMATED


def test_the_vocabulary_is_exactly_three_words():
    assert set(SESSION_KINDS) == {KIND_INTERACTIVE, KIND_AUTOMATED, KIND_UNKNOWN}


def test_a_title_alone_would_miss_this_scheduler_run():
    verdict = classify_records([SCHEDULER_ENQUEUE, SCHEDULER_USER])
    assert verdict.kind == KIND_AUTOMATED, (
        "the row whose title reads 'Urbackup completion proof' is a "
        "scheduler run and must be classified from the tag, not the title"
    )


from __future__ import annotations

from src.core.attention.pane_markers import (
    BLOCK_MAX_LINES,
    BLOCK_SEPARATOR_BLANK_LINES,
    QUESTION_DIALOG_MARKERS,
    classify_pane_tail,
    last_text_block,
)

PERMISSION_DIALOG_LINES = [
    "     Bash command",
    "",
    "       date +%s",
    "       Print current Unix timestamp",
    "",
    "     Ask rule Bash overrides auto mode for this command.",
    "",
    "   Do you want to proceed?",
    "   ❯ 1. Yes",
    "     2. No, and tell Claude what to do differently",
    "",
    "   Esc to cancel · Tab to amend",
]

QUESTION_FOOTER = "Enter to select · Tab/Arrow keys to navigate · Esc to cancel"

BUSY_FOOTER_LINES = [
    "⏸ plan mode on (shift+tab to cycle) · ← 1 agent",
    "◯ Explore the resolver 3m 43s · ↓ 121.8k tokens",
]

IDLE_PROMPT_LINES = [
    "─────────────────────────────────────────",
    "❯",
    "─────────────────────────────────────────",
    "⏵⏵ bypass permissions on (shift+tab to cycle)",
]


def test_permission_dialog_on_the_pane_is_matched() -> None:
    verdict = classify_pane_tail(PERMISSION_DIALOG_LINES)
    assert verdict.permission_dialog is True
    assert verdict.shows_dialog is True


def test_ask_user_question_footer_is_matched() -> None:
    verdict = classify_pane_tail(["   What should I do next?", "   " + QUESTION_FOOTER])
    assert verdict.question_dialog is True
    assert verdict.permission_dialog is False


def test_question_footer_tolerates_a_different_separator() -> None:
    swapped = "Enter to select | Tab/Arrow keys to navigate | Esc to cancel"
    assert classify_pane_tail([swapped]).question_dialog is True


def test_question_footer_is_anchored_to_its_own_line() -> None:
    prose = (
        "I will use Enter to select Tab/Arrow keys to navigate Esc to "
        "cancel when the menu opens."
    )
    assert classify_pane_tail([prose]).question_dialog is False


def test_busy_footer_matches_nothing() -> None:
    verdict = classify_pane_tail(BUSY_FOOTER_LINES)
    assert verdict.permission_dialog is False
    assert verdict.question_dialog is False
    assert verdict.trust_dialog is False
    assert verdict.shows_no_dialog is True


def test_idle_prompt_box_matches_nothing() -> None:
    verdict = classify_pane_tail(IDLE_PROMPT_LINES)
    assert verdict.shows_dialog is False
    assert verdict.shows_no_dialog is True


def test_folder_trust_dialog_is_its_own_family() -> None:
    verdict = classify_pane_tail(["  Yes, I trust this folder"])
    assert verdict.trust_dialog is True
    assert verdict.shows_dialog is False


def test_an_all_blank_capture_answers_none_not_false() -> None:
    verdict = classify_pane_tail(["", "   ", "\t", ""])
    assert verdict.permission_dialog is None
    assert verdict.question_dialog is None
    assert verdict.trust_dialog is None
    assert verdict.looked is False
    assert verdict.shows_no_dialog is False


def test_no_capture_at_all_answers_none() -> None:
    for capture in (None, []):
        verdict = classify_pane_tail(capture)
        assert verdict.permission_dialog is None
        assert verdict.looked is False


def test_a_dialog_in_stale_scrollback_is_not_matched() -> None:
    lines = PERMISSION_DIALOG_LINES + ["", "", "❯ carry on"]
    verdict = classify_pane_tail(lines)
    assert verdict.permission_dialog is False
    assert last_text_block(lines) == ["❯ carry on"]


def test_a_single_blank_line_does_not_split_a_dialog() -> None:
    assert BLOCK_SEPARATOR_BLANK_LINES == 2
    block = last_text_block(PERMISSION_DIALOG_LINES)
    assert "   Do you want to proceed?" in block
    assert "     Bash command" in block


def test_the_block_is_bounded_when_the_capture_has_no_separator() -> None:
    lines = ["line %d" % index for index in range(BLOCK_MAX_LINES * 3)]
    assert len(last_text_block(lines)) == BLOCK_MAX_LINES


def test_trailing_blanks_are_dropped_before_the_block_is_taken() -> None:
    assert last_text_block(["live", "", "", ""]) == ["live"]


def test_every_question_marker_is_compiled_and_anchored() -> None:
    for marker in QUESTION_DIALOG_MARKERS:
        assert hasattr(marker, "search"), marker
        assert marker.pattern.startswith("^")

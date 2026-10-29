
from __future__ import annotations

from src.core.attention.codex_pane import classify_codex_pane

DUST_IN_HEAD = "›⠁Ask Codex to do anything⡀"
CLEAN_REST = "› Ask Codex to do anything"


def test_dust_free_core_matches_even_with_braille_in_the_head():
    facts = classify_codex_pane(DUST_IN_HEAD)
    assert facts.resting_prompt is True


def test_clean_resting_prompt_matches():
    facts = classify_codex_pane(CLEAN_REST)
    assert facts.resting_prompt is True
    assert facts.approval_dialog is False


def test_a_spinner_in_the_title_is_working_not_resting():
    facts = classify_codex_pane(CLEAN_REST, pane_title="⠋ working")
    assert facts.working_marker is True
    assert facts.resting_prompt is False


def test_esc_to_interrupt_is_working():
    facts = classify_codex_pane("thinking (12s • esc to interrupt)")
    assert facts.working_marker is True
    assert facts.resting_prompt is False


def test_approval_dialog_is_matched():
    text = (
        "Would you like to run the following command?\n"
        "  rm -rf build\n"
        "> Yes, just this once\n"
        "  No, and tell Codex what to do differently\n"
        "press enter to confirm or esc to cancel"
    )
    facts = classify_codex_pane(text)
    assert facts.approval_dialog is True
    assert facts.resting_prompt is False


def test_action_required_title_is_an_approval():
    for title in ("[ ! ] Action Required", "[ . ] Action Required"):
        facts = classify_codex_pane("some scrollback", pane_title=title)
        assert facts.approval_dialog is True, title


def test_trust_dialog_is_matched_and_not_an_approval():
    text = (
        "> You are in /Users/x/proj\n"
        "Do you trust the contents of this directory?"
    )
    facts = classify_codex_pane(text)
    assert facts.trust_dialog is True
    assert facts.approval_dialog is False
    assert facts.resting_prompt is False


def test_a_blank_capture_is_all_none_not_a_clear_screen():
    facts = classify_codex_pane("   \n  \n")
    assert facts.resting_prompt is None
    assert facts.approval_dialog is None
    assert facts.trust_dialog is None


def test_read_screen_with_no_markers_is_measured_false_not_none():
    facts = classify_codex_pane("just some ordinary command output\n$ ls")
    assert facts.resting_prompt is False
    assert facts.approval_dialog is False
    assert facts.trust_dialog is False

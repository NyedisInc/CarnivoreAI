
from __future__ import annotations

import asyncio

import pytest

from src.core.approvals.answer import AnswerRefused, Choice, answer_dialog
from src.core.approvals.extract import extract_dialog
from src.core.approvals.plain_answer import plain_no_label, plain_yes_label, summary_line
from tests.python.approvals.pane_sim import ENTER, UP, PaneSim, fixture



def _dialog(name: str, family: str = "claude"):
    return extract_dialog(fixture(name), family)


def test_claude_bash_permission_has_plain_yes_and_no_and_a_summary():
    dialog = _dialog("claude_permission")
    assert plain_yes_label(dialog) == "Yes"
    assert plain_no_label(dialog) == "No"
    assert summary_line(dialog) == "Bash command: touch rigfile"


def test_codex_command_plain_yes_is_yes_proceed_never_dont_ask_again():
    dialog = _dialog("codex_command", "codex")
    assert plain_yes_label(dialog) == "Yes, proceed"
    assert plain_no_label(dialog).startswith("No, and tell Codex")
    assert summary_line(dialog) == "command: touch rigfile"


@pytest.mark.parametrize("name", ["claude_plan_narrow", "claude_single", "claude_multi", "claude_multi_question"])
def test_plan_and_question_dialogs_have_no_plain_yes(name):
    assert plain_yes_label(_dialog(name)) is None


def test_folder_trust_and_external_imports_have_no_plain_yes():
    from pathlib import Path

    startup = Path(__file__).resolve().parents[2] / "fixtures" / "startup_screens"
    for name in ("trust_dialog", "external_imports"):
        dialog = extract_dialog((startup / f"{name}.txt").read_text(), "claude")
        assert dialog is not None and plain_yes_label(dialog) is None, name


def _answer(pane: PaneSim, fingerprint: str, plain: str, family: str = "claude") -> None:
    asyncio.run(answer_dialog(family=family, fingerprint=fingerprint, choice=Choice(plain=plain),
                              capture=pane.capture, send=pane.send))


def test_matching_fingerprint_sends_yes():
    pane = PaneSim(fixture("claude_permission"))
    fingerprint = extract_dialog(pane.render(), "claude").fingerprint
    _answer(pane, fingerprint, "yes")
    assert pane.keys == [ENTER] and pane.pressed == 0


def test_a_cursor_on_dont_ask_again_is_moved_to_plain_yes_before_enter():
    pane = PaneSim(fixture("codex_command"))
    pane.move_cursor(1)
    fingerprint = extract_dialog(pane.render(), "codex").fingerprint
    _answer(pane, fingerprint, "yes", "codex")
    assert pane.keys == [UP, ENTER] and pane.pressed == 0


def test_changed_dialog_is_refused_and_sends_nothing():
    pane = PaneSim(fixture("claude_permission"))
    seen = extract_dialog(pane.render(), "claude").fingerprint
    pane.lines = [line.replace("touch rigfile", "rm -rf build") for line in pane.lines]
    with pytest.raises(AnswerRefused) as caught:
        _answer(pane, seen, "yes")
    assert caught.value.reason == "dialog_changed"
    assert pane.keys == [] and pane.pressed is None


def test_plain_yes_on_a_plan_dialog_is_refused_with_nothing_sent():
    pane = PaneSim(fixture("claude_plan_narrow"))
    fingerprint = extract_dialog(pane.render(), "claude").fingerprint
    with pytest.raises(AnswerRefused) as caught:
        _answer(pane, fingerprint, "yes")
    assert caught.value.reason == "no_plain_yes" and pane.keys == []


def test_plain_no_picks_the_decline_row_by_label():
    pane = PaneSim(fixture("claude_permission"))
    fingerprint = extract_dialog(pane.render(), "claude").fingerprint
    _answer(pane, fingerprint, "no")
    assert pane.pressed == 3 and pane.keys[-1] == ENTER

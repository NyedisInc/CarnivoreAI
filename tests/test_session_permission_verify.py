
from __future__ import annotations

import pytest

from src.core.session_permission_verify import detect_permission_dialog


_RULE = "\u2500" * 120
_DOTTED = "\u254c" * 120

BASH_DIALOG = "\n".join(
    [
        "  \u23bf  $ date +%s",
        "",
        _RULE,
        " Bash command",
        "",
        "   date +%s",
        "   Print current Unix timestamp",
        "",
        " Ask rule Bash overrides auto mode for this command.",
        " /permissions to let auto mode decide",
        "",
        " Do you want to proceed?",
        " \u276f 1. Yes",
        "   2. No",
        "",
        " Esc to cancel \u00b7 Tab to amend",
    ]
)

WRITE_DIALOG = "\n".join(
    [
        "\u276f use the Write tool to create note2.txt containing the word hello",
        "",
        "\u23fa Write(note2.txt)",
        "",
        _RULE,
        " Create file",
        " note2.txt",
        _DOTTED,
        "  1 hello",
        _DOTTED,
        " Do you want to create note2.txt?",
        " \u276f 1. Yes",
        "   2. No",
        "",
        " Esc to cancel \u00b7 Tab to amend",
    ]
)

IDLE_PANE = "\n".join(
    [
        _RULE,
        "\u276f",
        _RULE,
        "  jsugamele@mac-mini-m4:/private/tmp/claude-501/scratchpad\u2026",
        "  \u23f5\u23f5 auto mode on (shift+tab to cycle) \u00b7 \u2190 for agents",
        "                                                              /rc",
    ]
)

STUCK_LIVE_PANE = "\n".join(
    [
        "Permission allow rule (.claude/settings.json): Write(.claude/notes/**) is not matched by file permission checks \u2014 only Edit(",
        "",
        "                                                                                    new task? /clear to save 410.1k tokens",
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 Media Compression \u2500",
        "\u276f\xa0thats me, i have another session running",
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        "  jsugamele@mac-mini-m4:\u2302/\u2692/Assistants/Media \u2387(master) \u2726[Opus 5] \u25d0[\u2588\u2588\u2588\u2588\u2591\u2591\u2591\u2591\u2591\u2591]                                         /rc",
        "  \u23f5\u23f5 bypass permissions on (shift+tab to cycle) \xb7 \u2190 for agents",
    ]
)





@pytest.mark.parametrize(
    "tail,label",
    [(BASH_DIALOG, "bash"), (WRITE_DIALOG, "write")],
    ids=["bash-dialog", "write-dialog"],
)
def test_a_real_permission_dialog_is_detected(tail: str, label: str) -> None:
    assert detect_permission_dialog(tail) is True, label


@pytest.mark.parametrize(
    "tail,label",
    [(IDLE_PANE, "idle"), (STUCK_LIVE_PANE, "stuck-live")],
    ids=["idle-pane", "stuck-live-pane"],
)
def test_a_pane_with_no_dialog_is_not_detected(tail: str, label: str) -> None:
    assert detect_permission_dialog(tail) is False, label


def test_the_question_line_alone_is_enough_for_an_unseen_wording() -> None:
    assert detect_permission_dialog(
        " Do you want to make this edit to app.py?"
    ) is True


def test_the_phrase_mid_sentence_does_not_match() -> None:
    prose = (
        "I can refactor this next. Do you want to proceed with the "
        "migration first, or should I write the tests?"
    )
    assert detect_permission_dialog(prose) is False


def test_no_text_is_not_the_same_answer_as_no_dialog() -> None:
    assert detect_permission_dialog(None) is None
    assert detect_permission_dialog("") is False

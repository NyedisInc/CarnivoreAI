
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_osg_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_osg_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.session_one_shot_gate import (
    BODY_EMPTY,
    BODY_HAS_ESCAPE,
    BODY_NOT_UTF8,
    BODY_TOO_LARGE,
    MAX_BODY_BYTES,
    PANE_DIALOG_OPEN,
    PANE_NOT_AN_AGENT,
    PASTE_SAFE_STATUSES,
    CleanBody,
    OneShotRefused,
    check_can_paste,
    pane_command_is_agent,
    sanitize_body,
)
from src.core.session_startup_gate import (
    ALL_STARTUP_GATES,
    GATE_AWAITING,
    GATE_READY,
    GATE_UNKNOWN,
)
from src.core.session_status import (
    STATUS_DEAD,
    STATUS_FINISHED_UNREAD,
    STATUS_IDLE,
    STATUS_NOTICE,
    STATUS_QUESTION,
    STATUS_UNKNOWN,
    STATUS_WORKING,
    STATUS_WORKING_SUBAGENT,
)

SHELL_PANE_COMMAND = "zsh"
CODEX_PANE_COMMAND = "node"
CLAUDE_PANE_COMMAND = "2.1.266"


def _pass_kwargs(**overrides) -> dict:
    kwargs = {
        "pane_current_command": CODEX_PANE_COMMAND,
        "pane_dead": "0",
        "agent_type": "codex",
        "activity_status": STATUS_IDLE,
        "startup_gate": GATE_READY,
    }
    kwargs.update(overrides)
    return kwargs


def _try(**kwargs):
    try:
        check_can_paste(**kwargs)
    except OneShotRefused as refusal:
        return refusal
    return None




def test_the_three_measured_pane_commands_classify_as_recorded() -> None:
    assert pane_command_is_agent(SHELL_PANE_COMMAND) is False
    assert pane_command_is_agent(CODEX_PANE_COMMAND) is True
    assert pane_command_is_agent(CLAUDE_PANE_COMMAND) is True


@pytest.mark.parametrize("shell", ["zsh", "bash", "sh", "fish", "tcsh"])
def test_every_known_shell_is_refused(shell: str) -> None:
    assert pane_command_is_agent(shell) is False


@pytest.mark.parametrize("absent", [None, "", "   "])
def test_an_unread_pane_command_is_not_an_agent(absent) -> None:
    assert pane_command_is_agent(absent) is False




def test_all_four_signals_positive_passes() -> None:
    assert check_can_paste(**_pass_kwargs()) is None


def test_a_shell_pane_refuses_pane_not_an_agent() -> None:
    with pytest.raises(OneShotRefused) as caught:
        check_can_paste(**_pass_kwargs(pane_current_command=SHELL_PANE_COMMAND))
    assert caught.value.code == PANE_NOT_AN_AGENT


def test_an_unreadable_pane_refuses_pane_not_an_agent() -> None:
    with pytest.raises(OneShotRefused) as caught:
        check_can_paste(**_pass_kwargs(pane_current_command=None))
    assert caught.value.code == PANE_NOT_AN_AGENT


def test_a_measured_dead_pane_refuses_pane_not_an_agent() -> None:
    with pytest.raises(OneShotRefused) as caught:
        check_can_paste(**_pass_kwargs(pane_dead="1"))
    assert caught.value.code == PANE_NOT_AN_AGENT


def test_an_unread_pane_dead_flag_does_not_by_itself_refuse() -> None:
    assert check_can_paste(**_pass_kwargs(pane_dead=None)) is None


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_no_agent_record_on_the_row_refuses_pane_not_an_agent(empty) -> None:
    with pytest.raises(OneShotRefused) as caught:
        check_can_paste(**_pass_kwargs(agent_type=empty))
    assert caught.value.code == PANE_NOT_AN_AGENT




@pytest.mark.parametrize(
    "safe",
    [
        STATUS_IDLE,
        STATUS_FINISHED_UNREAD,
        STATUS_WORKING,
        STATUS_WORKING_SUBAGENT,
        STATUS_NOTICE,
    ],
)
def test_every_state_that_is_not_waiting_on_the_user_passes(safe: str) -> None:
    assert check_can_paste(**_pass_kwargs(activity_status=safe)) is None


def test_a_question_state_refuses_pane_dialog_open() -> None:
    with pytest.raises(OneShotRefused) as caught:
        check_can_paste(**_pass_kwargs(activity_status=STATUS_QUESTION))
    assert caught.value.code == PANE_DIALOG_OPEN


@pytest.mark.parametrize(
    "refused",
    [STATUS_QUESTION, STATUS_DEAD, STATUS_UNKNOWN, None, "", "a_state_we_invented"],
)
def test_every_state_that_is_not_positively_safe_refuses(refused) -> None:
    with pytest.raises(OneShotRefused) as caught:
        check_can_paste(**_pass_kwargs(activity_status=refused))
    assert caught.value.code == PANE_DIALOG_OPEN


def test_the_dialog_refusal_names_the_state_it_refused_on() -> None:
    with pytest.raises(OneShotRefused) as caught:
        check_can_paste(**_pass_kwargs(activity_status=STATUS_QUESTION))
    assert STATUS_QUESTION in caught.value.message


def test_the_safe_set_is_exactly_the_five_states_it_claims() -> None:
    assert PASTE_SAFE_STATUSES == frozenset(
        {
            STATUS_IDLE,
            STATUS_FINISHED_UNREAD,
            STATUS_WORKING,
            STATUS_WORKING_SUBAGENT,
            STATUS_NOTICE,
        }
    )
    assert STATUS_QUESTION not in PASTE_SAFE_STATUSES
    assert STATUS_UNKNOWN not in PASTE_SAFE_STATUSES
    assert STATUS_DEAD not in PASTE_SAFE_STATUSES




@pytest.mark.parametrize("refused", [GATE_AWAITING, GATE_UNKNOWN, None, "", "ready "])
def test_any_startup_gate_but_ready_refuses_pane_dialog_open(refused) -> None:
    with pytest.raises(OneShotRefused) as caught:
        check_can_paste(**_pass_kwargs(startup_gate=refused))
    assert caught.value.code == PANE_DIALOG_OPEN


def test_the_startup_refusal_names_the_gate_value() -> None:
    with pytest.raises(OneShotRefused) as caught:
        check_can_paste(**_pass_kwargs(startup_gate=GATE_AWAITING))
    assert GATE_AWAITING in caught.value.message


def test_only_one_of_the_three_startup_gate_values_passes() -> None:
    passing = [
        gate
        for gate in ALL_STARTUP_GATES
        if _try(**_pass_kwargs(startup_gate=gate)) is None
    ]
    assert passing == [GATE_READY]


def test_the_two_rungs_are_independent_questions() -> None:
    with pytest.raises(OneShotRefused):
        check_can_paste(
            **_pass_kwargs(activity_status=STATUS_QUESTION, startup_gate=GATE_READY)
        )
    with pytest.raises(OneShotRefused):
        check_can_paste(
            **_pass_kwargs(activity_status=STATUS_IDLE, startup_gate=GATE_AWAITING)
        )


def test_the_dialog_refusal_is_distinct_from_the_agent_refusal() -> None:
    assert PANE_DIALOG_OPEN != PANE_NOT_AN_AGENT




def test_a_plain_body_passes_through_unchanged() -> None:
    clean = sanitize_body("line one\nline two\twith a tab")
    assert isinstance(clean, CleanBody)
    assert clean.text == "line one\nline two\twith a tab"
    assert clean.stripped_count == 0
    assert clean.byte_length == len(clean.text.encode("utf-8"))


def test_an_escape_byte_is_refused_outright_and_never_stripped() -> None:
    with pytest.raises(OneShotRefused) as caught:
        sanitize_body("before\x1b[31mafter")
    assert caught.value.code == BODY_HAS_ESCAPE


def test_an_escape_anywhere_refuses_including_at_the_very_end() -> None:
    with pytest.raises(OneShotRefused) as caught:
        sanitize_body("a perfectly normal prompt\x1b")
    assert caught.value.code == BODY_HAS_ESCAPE


def test_other_control_characters_are_stripped_and_counted() -> None:
    clean = sanitize_body("a\x00b\x07c\x7fd\x9ee\nf\tg")
    assert clean.text == "abcde\nf\tg"
    assert clean.stripped_count == 4


def test_a_carriage_return_is_stripped_because_it_would_be_a_second_enter() -> None:
    clean = sanitize_body("first\r\nsecond\r\nthird")
    assert "\r" not in clean.text
    assert clean.text == "first\nsecond\nthird"
    assert clean.stripped_count == 2


def test_the_stripped_count_is_zero_when_nothing_was_removed() -> None:
    assert sanitize_body("nothing to strip here").stripped_count == 0


def test_the_byte_length_describes_the_cleaned_text_not_the_raw_body() -> None:
    clean = sanitize_body("ab\x00cd")
    assert clean.byte_length == len("abcd".encode("utf-8"))


def test_a_multibyte_body_measures_bytes_not_characters() -> None:
    clean = sanitize_body("héllo")
    assert clean.byte_length == 6
    assert len(clean.text) == 5


@pytest.mark.parametrize("empty", ["", "   ", "\n\n", "\t"])
def test_an_empty_body_is_refused(empty: str) -> None:
    with pytest.raises(OneShotRefused) as caught:
        sanitize_body(empty)
    assert caught.value.code == BODY_EMPTY


def test_a_body_of_nothing_but_control_characters_is_refused_as_empty() -> None:
    with pytest.raises(OneShotRefused) as caught:
        sanitize_body("\x00\x01\x02")
    assert caught.value.code == BODY_EMPTY


def test_a_body_over_the_cap_is_refused() -> None:
    with pytest.raises(OneShotRefused) as caught:
        sanitize_body("x" * (MAX_BODY_BYTES + 1))
    assert caught.value.code == BODY_TOO_LARGE


def test_a_body_exactly_at_the_cap_is_accepted() -> None:
    assert sanitize_body("x" * MAX_BODY_BYTES).byte_length == MAX_BODY_BYTES


def test_a_lone_surrogate_body_is_refused_rather_than_crashing() -> None:
    with pytest.raises(OneShotRefused) as caught:
        sanitize_body("hello \ud800 world")
    assert caught.value.code == BODY_NOT_UTF8
    assert "not valid utf-8" in caught.value.message


def test_a_surrogate_pair_spelled_out_in_json_is_still_refused() -> None:
    with pytest.raises(OneShotRefused) as caught:
        sanitize_body("\ud83d")
    assert caught.value.code == BODY_NOT_UTF8


def test_a_real_astral_character_still_passes() -> None:
    clean = sanitize_body("a \U0001f600 b")
    assert clean.byte_length == len("a \U0001f600 b".encode("utf-8"))


def test_the_refusal_carries_a_sentence_beside_its_code() -> None:
    with pytest.raises(OneShotRefused) as caught:
        sanitize_body("\x1b")
    assert caught.value.code == BODY_HAS_ESCAPE
    assert caught.value.message.strip()
    assert str(caught.value) == caught.value.message

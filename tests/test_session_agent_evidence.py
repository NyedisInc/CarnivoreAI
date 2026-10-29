
import pytest

from src.core.agent_family_display import resolve_family_for_display
from src.core.agent_wrapper_display import resolve_wrapper_for_display
from src.core.session_agent_evidence import (
    BASIS_MEMORY_FINGERPRINT,
    BASIS_MEMORY_LAUNCH,
    BASIS_NONE,
    BASIS_RECORDED_ROW,
    choose_agent_evidence,
)

WRAPPERS = [
    {"id": "claude-skip-permissions", "label": "claude", "family": "claude"},
    {"id": "claude-chrome", "label": "claude (chrome)", "family": "claude"},
]


def test_a_recorded_row_beats_an_in_memory_fingerprint():
    got = choose_agent_evidence(
        memory_agent_type="claude",
        memory_from_fingerprint=True,
        row_agent_type="claude-chrome",
    )
    assert got.agent_type == "claude-chrome"
    assert got.from_fingerprint is False
    assert got.basis == BASIS_RECORDED_ROW


def test_row_43_renders_a_solid_claude_family_and_names_its_wrapper():
    got = choose_agent_evidence(
        memory_agent_type="claude",
        memory_from_fingerprint=True,
        row_agent_type="claude-chrome",
    )
    family, source = resolve_family_for_display(
        got.agent_type, WRAPPERS, from_fingerprint=got.from_fingerprint
    )
    wrapper = resolve_wrapper_for_display(
        got.agent_type, WRAPPERS, from_fingerprint=got.from_fingerprint
    )
    assert family is not None and family.name == "claude"
    assert source == "wrapper"
    assert wrapper.label == "claude (chrome)"


def test_an_in_memory_launch_outranks_the_row():
    got = choose_agent_evidence(
        memory_agent_type="clxor",
        memory_from_fingerprint=False,
        row_agent_type="claude-chrome",
    )
    assert got.agent_type == "clxor"
    assert got.from_fingerprint is False
    assert got.basis == BASIS_MEMORY_LAUNCH


def test_an_empty_memory_still_falls_back_to_the_row():
    got = choose_agent_evidence(
        memory_agent_type=None,
        memory_from_fingerprint=False,
        row_agent_type="claude-chrome",
    )
    assert got.agent_type == "claude-chrome"
    assert got.from_fingerprint is False
    assert got.basis == BASIS_RECORDED_ROW


def test_a_fingerprint_survives_when_the_row_records_nothing():
    got = choose_agent_evidence(
        memory_agent_type="claude",
        memory_from_fingerprint=True,
        row_agent_type=None,
    )
    assert got.agent_type == "claude"
    assert got.from_fingerprint is True
    assert got.basis == BASIS_MEMORY_FINGERPRINT


def test_a_surviving_fingerprint_still_paints_a_guess_pill():
    got = choose_agent_evidence(
        memory_agent_type="claude",
        memory_from_fingerprint=True,
        row_agent_type=None,
    )
    _family, source = resolve_family_for_display(
        got.agent_type, WRAPPERS, from_fingerprint=got.from_fingerprint
    )
    assert source == "fingerprint"


@pytest.mark.parametrize("row_value", [None, "", "   "])
def test_both_sources_empty_answers_nothing_and_never_guesses(row_value):
    got = choose_agent_evidence(
        memory_agent_type=None,
        memory_from_fingerprint=False,
        row_agent_type=row_value,
    )
    assert got.agent_type is None
    assert got.from_fingerprint is False
    assert got.basis == BASIS_NONE


def test_nothing_resolves_to_unknown_family_and_no_wrapper_pill():
    got = choose_agent_evidence(
        memory_agent_type=None,
        memory_from_fingerprint=False,
        row_agent_type=None,
    )
    family, source = resolve_family_for_display(
        got.agent_type, WRAPPERS, from_fingerprint=got.from_fingerprint
    )
    wrapper = resolve_wrapper_for_display(
        got.agent_type, WRAPPERS, from_fingerprint=got.from_fingerprint
    )
    assert family is None
    assert source == "unknown"
    assert wrapper.label is None


@pytest.mark.parametrize("memory_value", ["", "   "])
def test_a_blank_in_memory_value_is_an_absence_not_a_launch(memory_value):
    got = choose_agent_evidence(
        memory_agent_type=memory_value,
        memory_from_fingerprint=False,
        row_agent_type="claude-chrome",
    )
    assert got.agent_type == "claude-chrome"
    assert got.basis == BASIS_RECORDED_ROW

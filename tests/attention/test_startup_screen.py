
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.attention.pane_markers import classify_pane_tail
from src.core.attention.registry_record import REG_SHAPE_UNRECOGNIZED
from src.core.attention.startup_screen import (
    FALLBACK_HOLD_SECONDS,
    StartupScreenMemory,
    agent_alive_under,
    classify_startup_screen,
    gate_with_screen,
    read_startup_screen,
)
from src.core.session_startup_gate import (
    GATE_AWAITING,
    GATE_READY,
    SCREEN_UNRECOGNIZED,
    detect_startup_prompt,
    startup_screen_kind,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "startup_screens"
NOW = datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc)


def _screen(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("fixture, kind", [
    ("trust_dialog.txt", "trust"),
    ("mcp_server_approval.txt", "mcp_server"),
    ("external_imports.txt", "external_imports"),
    ("bypass_permissions_warning.txt", "bypass_permissions"),
    ("resume_picker.txt", "resume_picker"),
    ("onboarding_theme.txt", "onboarding_theme"),
    ("onboarding_login_method.txt", "login_method"),
])
def test_every_captured_startup_screen_is_named(fixture: str, kind: str) -> None:
    text = _screen(fixture)
    assert startup_screen_kind(text) == kind
    assert detect_startup_prompt(text) is True


def test_inline_release_notes_at_a_working_prompt_are_not_a_startup_screen() -> None:
    text = _screen("release_notes_inline_resting.txt")
    assert startup_screen_kind(text) is None
    assert detect_startup_prompt(text) is False


def _classify(text, *, present=False, absent=True, alive=True):
    resting = classify_pane_tail(text.splitlines()).resting_prompt
    return classify_startup_screen(text, registry_present=present, record_absent=absent,
                                   agent_alive=alive, resting=resting)


def test_a_record_outranks_any_screen_text() -> None:
    assert _classify(_screen("trust_dialog.txt"), present=True) is None


def test_a_dead_agent_is_not_waiting_on_a_screen() -> None:
    assert _classify(_screen("mcp_server_approval.txt"), alive=False) is None


def test_the_resume_picker_record_without_status_still_lets_its_marker_through() -> None:
    assert _classify(_screen("resume_picker.txt"), absent=False) == ("resume_picker", True)


def test_fallback_names_an_unknown_blocking_screen() -> None:
    text = "Some brand new claude notice\n  1. Continue\n  2. Not now\n"
    assert _classify(text) == (SCREEN_UNRECOGNIZED, False)


def test_fallback_needs_a_measured_live_agent_and_no_record_file() -> None:
    text = "Some brand new claude notice\n  1. Continue\n  2. Not now\n"
    assert _classify(text, alive=None) is None
    assert _classify(text, absent=False) is None
    assert _classify(_screen("release_notes_inline_resting.txt")) is None


def test_fallback_holds_before_it_is_shown_and_a_marker_does_not() -> None:
    memory = StartupScreenMemory()
    inst = ("s", "n", 1, 9)
    first = memory.observe("ses_1", inst, (SCREEN_UNRECOGNIZED, False), "x", NOW)
    assert first is not None and not first.shown(NOW)
    later = NOW + timedelta(seconds=FALLBACK_HOLD_SECONDS)
    assert memory.observe("ses_1", inst, (SCREEN_UNRECOGNIZED, False), "x", later).shown(later)
    assert not memory.observe("ses_1", ("s", "n", 1, 10), (SCREEN_UNRECOGNIZED, False), "x", later).shown(later)
    assert memory.observe("ses_2", inst, ("trust", True), "x", NOW).shown(NOW)


def test_agent_alive_walks_the_pane_tree() -> None:
    parents = {11: 10, 12: 11, 20: 1}
    commands = {11: "zsh -c source w", 12: "/Users/x/.local/bin/claude --resume u", 20: "claude"}
    assert agent_alive_under(10, parents, commands, True) is True
    assert agent_alive_under(30, parents, commands, True) is False
    assert agent_alive_under(10, parents, commands, False) is None


def test_reader_call_and_the_listing_gate_project_one_observation() -> None:
    memory = StartupScreenMemory()
    registry = SimpleNamespace(instance_present=False, verdict=REG_SHAPE_UNRECOGNIZED)
    text = _screen("resume_picker.txt")
    table = SimpleNamespace(parents={2: 1}, commands={2: "claude --resume"}, ok=True)
    screen = read_startup_screen(memory, "ses_1", text=text, registry=registry,
                                 pane=classify_pane_tail(text.splitlines()), pane_pid=1,
                                 snapshot=lambda: table, instance=("s", "n", 1, 1), now=NOW)
    assert screen is not None and screen.kind == "resume_picker" and "Resume session" in screen.text
    observation = SimpleNamespace(stale=False, evidence=SimpleNamespace(startup_screen=screen, now=NOW))
    assert gate_with_screen(GATE_READY, observation) == GATE_AWAITING
    observation.stale = True
    assert gate_with_screen(GATE_READY, observation) == GATE_READY
    assert gate_with_screen(GATE_READY, None) == GATE_READY
    started = SimpleNamespace(instance_present=True, verdict="ok")
    assert read_startup_screen(memory, "ses_1", text=text, registry=started, pane=None, pane_pid=1,
                               snapshot=lambda: table, instance=("s", "n", 1, 1), now=NOW) is None

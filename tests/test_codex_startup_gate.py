
from __future__ import annotations

from src.core.session_startup_gate import (
    GATE_AWAITING,
    GATE_READY,
    detect_startup_prompt,
    resolve_startup_gate,
)

CODEX_TRUST = (
    "> You are in /Users/x/proj\n"
    "Do you trust the contents of this directory?\n"
    "> Yes, allow Codex to work here\n"
    "  No, choose a different folder"
)


def test_codex_trust_dialog_is_detected_as_a_startup_prompt():
    assert detect_startup_prompt(CODEX_TRUST) is True


def test_a_starting_codex_pane_reads_awaiting_not_unknown():
    verdict = resolve_startup_gate(
        pane_alive=True,
        first_hook_at=None,
        instance_age_seconds=60.0,
        tail=CODEX_TRUST,
    )
    assert verdict == GATE_AWAITING


def test_ordinary_codex_output_is_not_a_startup_prompt():
    verdict = resolve_startup_gate(
        pane_alive=True,
        first_hook_at=None,
        instance_age_seconds=60.0,
        tail="› Ask Codex to do anything",
    )
    assert verdict == GATE_READY

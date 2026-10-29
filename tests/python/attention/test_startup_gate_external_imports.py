
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sgx_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sgx_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.session_startup_gate import (
    GATE_AWAITING,
    GATE_READY,
    STARTUP_HOOK_GRACE_SECONDS,
    detect_startup_prompt,
    resolve_startup_gate,
)

IMPORTS_PROMPT_TAIL = """
 Allow external CLAUDE.md file imports?

 This project's CLAUDE.md or .claude/rules imports files outside the current
 working directory. Never allow this for third-party repositories.

 External imports:
   /Users/someone/shared/rules.md

 ❯ Yes, allow external imports
   No, disable external imports
"""

WRAPPED_TAIL = (
    " Allow external CLAUDE.md\n file imports?\n\n"
    " ❯ Yes, allow external imports\n   No, disable external imports\n"
)

STEADY_STATE_TAIL = "  ? for shortcuts\n  ⏵⏵ auto mode on (shift+tab to cycle)\n"


def test_matcher_finds_the_external_imports_dialog():
    assert detect_startup_prompt(IMPORTS_PROMPT_TAIL) is True


def test_matcher_survives_a_wrapped_question():
    assert detect_startup_prompt(WRAPPED_TAIL) is True


def test_matcher_negative_control():
    assert detect_startup_prompt(STEADY_STATE_TAIL) is False


def test_gate_is_awaiting_for_a_hookless_pane_on_the_dialog():
    verdict = resolve_startup_gate(
        pane_alive=True,
        first_hook_at=None,
        instance_age_seconds=float(STARTUP_HOOK_GRACE_SECONDS + 5),
        tail=IMPORTS_PROMPT_TAIL,
    )
    assert verdict == GATE_AWAITING


def test_gate_is_ready_on_the_steady_state_tail():
    verdict = resolve_startup_gate(
        pane_alive=True,
        first_hook_at=None,
        instance_age_seconds=float(STARTUP_HOOK_GRACE_SECONDS + 5),
        tail=STEADY_STATE_TAIL,
    )
    assert verdict == GATE_READY

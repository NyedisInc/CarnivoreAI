
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List

from src.core.approvals.extract import KIND_TRUST, extract_dialog
from src.core.notifications.sources.approvals import ApprovalsSource, is_folder_trust_dialog
from tests.test_session_startup_gate import TRUST_PROMPT_TAIL
from tests.python.notifications.test_sources_approvals_alerts import _Provider, _manager  # noqa: F401

NUMBERED = TRUST_PROMPT_TAIL.replace("❯ No, exit", "❯ 1. No, exit").replace("   Yes, I trust", "  2. Yes, I trust")
MODEL_PICKER = """
 Select model

 ❯ 1. Default (recommended)
   2. Opus

 Enter to confirm · Esc to cancel
"""
TRUST_UTILS_PERMISSION = """
 Edit file src/trust_utils.py

 Do you want to make this edit to trust_utils.py?
 ❯ 1. Yes
   2. No

 Esc to cancel
"""


def test_real_claude_trust_screen_extracts_as_trust_numbered_or_not() -> None:
    for screen in (TRUST_PROMPT_TAIL, NUMBERED):
        dialog = extract_dialog(screen, "claude")
        assert dialog is not None and dialog.kind == KIND_TRUST
        assert [r.label for r in dialog.rows] == ["No, exit", "Yes, I trust this folder"] and dialog.cursor == 0
        assert is_folder_trust_dialog(dialog) is True


def test_other_claude_screens_are_not_trust() -> None:
    assert extract_dialog(MODEL_PICKER, "claude") is None
    perm = extract_dialog(TRUST_UTILS_PERMISSION, "claude")
    assert perm is not None and is_folder_trust_dialog(perm) is False


def test_trust_fingerprint_follows_the_folder() -> None:
    a = extract_dialog(TRUST_PROMPT_TAIL, "claude")
    b = extract_dialog(TRUST_PROMPT_TAIL.replace("workdir", "other"), "claude")
    assert a.fingerprint != b.fingerprint and a.fingerprint == extract_dialog(TRUST_PROMPT_TAIL, "claude").fingerprint


def _emitted(screen: str, captured: List[Any]) -> None:
    dialog = extract_dialog(screen, "claude")
    obs = SimpleNamespace(evidence=SimpleNamespace(dialog=dialog))
    watcher = SimpleNamespace(observation_for=lambda s: obs)
    source = ApprovalsSource(lambda: watcher, _manager, lambda: SimpleNamespace(list=lambda: []))
    source.on_gain([("dialog", "dlg:ses_1:ab12")])


def test_claude_trust_emits_once_and_a_permission_about_trust_utils_emits_nothing(captured) -> None:
    _emitted(TRUST_PROMPT_TAIL, captured)
    assert [e.type_id for e in captured] == ["approval.folder_trust"]
    captured.clear()
    _emitted(TRUST_UTILS_PERMISSION, captured)
    assert captured == []


def test_codex_trust_still_extracts() -> None:
    codex = """
 Do you trust the contents of this directory?

 › 1. Yes, continue
   2. No, quit

 Press enter to continue
"""
    dialog = extract_dialog(codex, "codex")
    assert dialog is not None and dialog.kind == KIND_TRUST

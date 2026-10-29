
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

import pytest

from src.core.approvals.answer import AnswerRefused, Choice, answer_dialog
from src.core.approvals.extract import KIND_OTHER, KIND_PERMISSION, KIND_TRUST, extract_dialog
from src.core.approvals.startup_extract import answer_needs_owner
from src.core.beast_prompts.engine import eligible_dialog
from src.core.swarm.auto_trust import is_claude_trust_dialog

SCREENS = Path(__file__).resolve().parents[2] / "fixtures" / "startup_screens"
DOWN, UP, ENTER = "\x1b[B", "\x1b[A", "\r"
_GLYPH_ROW = re.compile(r"^(\s*)❯ (\S.*)$")


def screen(name: str) -> str:
    return (SCREENS / f"{name}.txt").read_text()


class StartupPane:

    def __init__(self, text: str) -> None:
        self.lines = text.split("\n")
        foot = max(i for i, ln in enumerate(self.lines) if ln.strip().startswith("Enter to confirm"))
        end = foot
        while not self.lines[end - 1].strip():
            end -= 1
        start = end
        while self.lines[start - 1].strip():
            start -= 1
        self.rows = list(range(start, end))
        self.cursor = next(n for n, i in enumerate(self.rows) if _GLYPH_ROW.match(self.lines[i]))
        indent = _GLYPH_ROW.match(self.lines[self.rows[self.cursor]]).group(1)
        self.labels = [self.lines[i].strip().lstrip("❯").strip() for i in self.rows]
        self.indent = indent
        self.keys: List[str] = []
        self.pressed: Optional[str] = None

    async def capture(self) -> str:
        out = list(self.lines)
        for n, i in enumerate(self.rows):
            out[i] = f"{self.indent}{'❯ ' if n == self.cursor else '  '}{self.labels[n]}"
        return "\n".join(out)

    async def send(self, key: str) -> None:
        self.keys.append(key)
        if key == DOWN:
            self.cursor = min(len(self.rows) - 1, self.cursor + 1)
        elif key == UP:
            self.cursor = max(0, self.cursor - 1)
        elif key == ENTER:
            self.pressed = self.labels[self.cursor]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def instant(_seconds: float) -> None:
        return None
    monkeypatch.setattr("src.core.approvals.answer.asyncio.sleep", instant)


def test_the_incident_trust_variant_decodes_with_its_options_warning_and_fingerprint() -> None:
    dialog = extract_dialog(screen("trust_dialog_permissions"), "claude")
    assert dialog is not None and dialog.kind == KIND_TRUST and dialog.startup_kind == "trust"
    assert list(dialog.options) == ["No, continue without these permissions", "Yes, I trust this folder"]
    assert dialog.cursor == 0 and re.fullmatch(r"[0-9a-f]{64}", dialog.fingerprint)
    assert "pre-approves 4 tool permissions" in dialog.body
    assert dialog.to_dict()["startup_kind"] == "trust"


@pytest.mark.parametrize("name, kind, startup_kind, options", [
    ("trust_dialog", KIND_TRUST, "trust", ["No, exit", "Yes, I trust this folder"]),
    ("mcp_server_approval", KIND_OTHER, "mcp_server",
     ["Use this MCP server", "Use this and all future MCP servers in this project", "Continue without using this MCP server"]),
    ("bypass_permissions_warning", KIND_OTHER, "bypass_permissions", ["No, exit", "Yes, I accept"]),
    ("external_imports", KIND_OTHER, "external_imports", ["No, disable external imports", "Yes, allow external imports"]),
])
def test_every_named_confirm_screen_shows_its_options_in_screen_order(name, kind, startup_kind, options) -> None:
    dialog = extract_dialog(screen(name), "claude")
    assert dialog is not None and dialog.kind == kind and dialog.startup_kind == startup_kind
    assert list(dialog.options) == options


@pytest.mark.parametrize("name", ["onboarding_login_method", "onboarding_theme", "resume_picker",
                                  "release_notes_inline_resting"])
def test_a_screen_without_a_readable_option_block_stays_read_only(name) -> None:
    assert extract_dialog(screen(name), "claude") is None


def test_a_wrapped_row_or_a_screen_with_only_the_shared_footer_is_never_guessed() -> None:
    wrapped = screen("mcp_server_approval").replace(
        "    Use this and all future MCP servers in this project",
        "    Use this and all future MCP servers in\n      this project")
    assert extract_dialog(wrapped, "claude") is None
    picker = "\n Select model\n\n ❯ Default (recommended)\n   Opus\n\n Enter to confirm · Esc to cancel\n"
    assert extract_dialog(picker, "claude") is None


def test_pressing_an_option_presses_exactly_that_label() -> None:
    pane = StartupPane(screen("trust_dialog_permissions"))
    dialog = extract_dialog(asyncio.run(pane.capture()), "claude")
    asyncio.run(answer_dialog(family="claude", fingerprint=dialog.fingerprint,
                              choice=Choice(option="Yes, I trust this folder"), capture=pane.capture, send=pane.send))
    assert pane.pressed == "Yes, I trust this folder" and pane.keys == [DOWN, ENTER]


def test_the_mcp_screen_presses_a_row_above_the_cursor() -> None:
    pane = StartupPane(screen("mcp_server_approval"))
    dialog = extract_dialog(asyncio.run(pane.capture()), "claude")
    asyncio.run(answer_dialog(family="claude", fingerprint=dialog.fingerprint,
                              choice=Choice(option="Use this MCP server"), capture=pane.capture, send=pane.send))
    assert pane.pressed == "Use this MCP server" and pane.keys == [UP, UP, ENTER]


def test_a_stale_fingerprint_refuses_and_sends_nothing() -> None:
    pane = StartupPane(screen("trust_dialog_permissions"))
    seen = extract_dialog(asyncio.run(pane.capture()), "claude")
    other_folder = StartupPane(screen("trust_dialog_permissions").replace("Org/Example/Project", "Org/Other/Repo"))
    assert extract_dialog(asyncio.run(other_folder.capture()), "claude").fingerprint != seen.fingerprint
    with pytest.raises(AnswerRefused) as refused:
        asyncio.run(answer_dialog(family="claude", fingerprint=seen.fingerprint,
                                  choice=Choice(option="Yes, I trust this folder"),
                                  capture=other_folder.capture, send=other_folder.send))
    assert refused.value.reason == "dialog_changed" and other_folder.keys == [] and other_folder.pressed is None


def _observation(dialog, startup_screen=None) -> SimpleNamespace:
    return SimpleNamespace(stale=False, evidence=SimpleNamespace(dialog=dialog, startup_screen=startup_screen))


@pytest.mark.parametrize("name", ["trust_dialog", "trust_dialog_permissions", "mcp_server_approval",
                                  "bypass_permissions_warning", "external_imports"])
def test_beast_mode_never_answers_a_startup_screen(name) -> None:
    dialog = extract_dialog(screen(name), "claude")
    assert answer_needs_owner(dialog) is True
    assert eligible_dialog(_observation(dialog, startup_screen=object())) is None
    assert eligible_dialog(_observation(dialog)) is None


def test_the_startup_guard_holds_even_for_a_dialog_with_a_plain_yes() -> None:
    plain = extract_dialog(screen("bypass_permissions_warning"), "claude")
    forged = plain.__class__(**{**plain.__dict__, "kind": KIND_PERMISSION,
                                "rows": tuple(r.__class__(**{**r.__dict__, "label": "Yes"}) if i else r
                                              for i, r in enumerate(plain.rows))})
    assert eligible_dialog(_observation(forged)) is None
    assert eligible_dialog(_observation(forged.__class__(**{**forged.__dict__, "startup_kind": None}))) is not None


def test_swarm_auto_trust_still_refuses_the_permissions_variant() -> None:
    assert is_claude_trust_dialog(extract_dialog(screen("trust_dialog"), "claude")) is True
    assert is_claude_trust_dialog(extract_dialog(screen("trust_dialog_permissions"), "claude")) is False

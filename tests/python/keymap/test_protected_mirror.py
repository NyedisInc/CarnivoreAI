
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.core.keymap import protected

REPO = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is needed to read the browser's registry")

CASES = [
    ("mac", "cmd+j"), ("mac", "ctrl+c"), ("mac", "cmd+c"), ("mac", "j"), ("mac", "escape"), ("mac", "tab"), ("mac", "alt+cmd+k"),
    ("other", "ctrl+shift+j"), ("other", "ctrl+alt+j"), ("other", "ctrl+j"), ("other", "alt+j"), ("other", "j"), ("other", "ctrl+w"),
    ("other", "ctrl+shift+t"), ("other", "enter"), ("mac", "CMD+J"), ("mac", "cmd+shift+j"),
    ("other", "ctrl+shift+c"), ("other", "ctrl+shift+v"), ("mac", "cmd+f"), ("mac", "cmd+g"), ("other", "ctrl+f"),
    ("other", "shift+enter"), ("mac", "arrowup"), ("other", "ctrl+alt+shift+j"), ("mac", "ctrl+j"), ("other", "ctrl+shift+j"),
]
IDS = {"global": "history.back", "terminal-pane": "terminal.copy", "terminal-screen": "terminal.zoom.toggle", "electron-menu": "desktop.quit",
       "os-global": "desktop.hotkey", "field": "form.submit", "menu": "menu.rename", "menu:rail": "nav.home", "list:feed": "feed.next",
       "overlay:palette": "palette.next"}


def _node(script: str) -> object:
    out = subprocess.run(["node", "--input-type=module", "-e", script], cwd=REPO, capture_output=True, text=True, check=True, timeout=60)
    return json.loads(out.stdout)


def test_reserved_lists_match() -> None:
    js = _node("const p = await import('./client/js/keymap/protected.js'); console.log(JSON.stringify(p.RESERVED))")
    assert {k: sorted(v) for k, v in js.items()} == {k: sorted(v) for k, v in protected.RESERVED.items()}


def test_every_action_is_classified_the_same_way_in_both() -> None:
    actions = _node(
        "const a = await import('./client/js/keymap/actions.js'); const p = await import('./client/js/keymap/protected.js');"
        "console.log(JSON.stringify(a.ACTIONS.map((x) => [x.id, p.reachesTerminal(x.scope)])))"
    )
    assert len(actions) > 150
    wrong = [i for i, reach in actions if protected.reaches_terminal(i) != reach and not i.startswith(("mouse.", "standard."))]
    assert wrong == []


@pytest.mark.parametrize("scope", sorted(IDS))
def test_refusal_agrees_for_every_case(scope: str) -> None:
    js = _node(
        "const p = await import('./client/js/keymap/protected.js'); const a = await import('./client/js/keymap/actions.js');"
        f"console.log(JSON.stringify({json.dumps(CASES)}.map(([f, c]) => p.refusal(f, c, {json.dumps(scope)}, a.ACTIONS))))"
    )
    assert js == [protected.refusal(family, chord, IDS[scope]) for family, chord in CASES]


def test_terminal_owned_chords_are_exactly_what_the_registry_binds_in_the_terminal_and_text_boxes() -> None:
    js = _node(
        "const a = await import('./client/js/keymap/actions.js'); const p = await import('./client/js/keymap/protected.js');"
        "console.log(JSON.stringify({mac: p.terminalOwned(a.ACTIONS, 'mac'), other: p.terminalOwned(a.ACTIONS, 'other')}))"
    )
    assert {k: sorted(v) for k, v in js.items()} == {k: sorted(v) for k, v in protected.TERMINAL_OWNED.items()}


def test_text_input_actions_are_classified_the_same_way_in_both() -> None:
    actions = _node(
        "const a = await import('./client/js/keymap/actions.js'); const p = await import('./client/js/keymap/protected.js');"
        "console.log(JSON.stringify(a.ACTIONS.map((x) => [x.id, p.inTextInput(x.scope)])))"
    )
    wrong = [i for i, text in actions if protected.in_text_input(i) != text and not i.startswith(("mouse.", "standard."))]
    assert wrong == []


def test_the_terminals_own_copy_and_paste_and_search_cannot_be_taken_by_a_global_action() -> None:
    for family, chord in (("other", "ctrl+shift+c"), ("other", "ctrl+shift+v"), ("mac", "cmd+f")):
        assert protected.refusal(family, chord, "history.back") is not None, chord


def test_off_a_mac_ctrl_with_alt_is_refused_and_a_bare_key_in_a_text_box_is_refused() -> None:
    assert protected.refusal("other", "ctrl+alt+j", "history.back") == "no_ctrl_alt"
    assert protected.refusal("mac", "j", "form.submit") == "needs_modifier"
    assert protected.refusal("mac", "j", "palette.next") == "needs_modifier"
    assert protected.refusal("mac", "j", "terminal.search.next") == "needs_modifier"
    assert protected.refusal("mac", "j", "menu.rename") is None

from __future__ import annotations

import functools
import re
import sys
from pathlib import Path

from tests.python.design_system._sources import REPO, css_of

ALLOWED = frozenset({
    "auth-button",
    "btn-icon", "command-button-desc",
    "command-button-name", "folder-picker-navbtn",
    "modal-btn", "modal-btn-alert",
    "modal-btn-confirm", "modal-btn-danger", "modal-btn-primary",
    "modal-btn-secondary", "oc-btn", "snd-btn",
    "oc-ibtn",
})
_CLASS = re.compile(r"\.([A-Za-z][\w-]*)")
_BUTTON_CLASS = re.compile(
    r"(?:\bbutton|\[role=[\"']?button[\"']?\])\.([A-Za-z][\w-]*)"
    r"|\.([A-Za-z][\w-]*)\[role=[\"']?button[\"']?\]"
)
_STATE = re.compile(r":(?:hover|active|focus|focus-visible)\b|\[(?:aria-pressed|aria-current|aria-expanded|aria-selected|data-active)")
OLD_ROOTS = ("client/css", "web/src")
SCAN_ROOTS = (*OLD_ROOTS, "src/cplugs", "hosted", "macOS")

KNOWN_WIDENED = frozenset({
    "ap-hc", "d-ev__btn", "d-vl__row", "hd-slot-key", "row-badge",
    "session-sidebar-row-wake-icon", "sp-pic", "sw-btn", "themes-now",
    "toast__session", "tool-zoom-armed", "uw-btn",
})


def stateful_button_bases(css: str) -> set[str]:
    found: set[str] = set()
    for selector in re.findall(r"([^{}]+)\{", css):
        if not _STATE.search(selector):
            continue
        for match in _BUTTON_CLASS.finditer(selector):
            name = match.group(1) or match.group(2)
            if "--" not in name:
                found.add(name)
    return found


def button_bases(css: str) -> set[str]:
    found: set[str] = set()
    for selector in re.findall(r"([^{}]+)\{", css):
        for name in _CLASS.findall(selector):
            if re.search(r"btn|button", name) and "__" not in name and "--" not in name:
                found.add(name)
    return found


def shipped_button_bases() -> set[str]:
    found: set[str] = set()
    for css in _shipped_css(OLD_ROOTS):
        found |= button_bases(css)
    return found


def widened_families() -> set[str]:
    found: set[str] = set()
    for css in _shipped_css(SCAN_ROOTS):
        found |= stateful_button_bases(css)
    for css in _shipped_css(SCAN_ROOTS[len(OLD_ROOTS):]):
        found |= button_bases(css)
    return found - ALLOWED


def _shipped_css(roots: tuple[str, ...]) -> list[str]:
    sheets: list[str] = []
    for root in roots:
        sheets += _root_css(REPO, root)
    return sheets


@functools.lru_cache(maxsize=None)
def _root_css(repo: Path, root: str) -> list[str]:
    sheets: list[str] = []
    for path in (repo / root).rglob("*"):
        if path.is_file() and "node_modules" not in path.parts and "dist" not in path.parts:
            sheets.append(css_of(path))
    return sheets


def test_no_new_button_family() -> None:
    new = shipped_button_bases() - ALLOWED
    assert not new, f"new button family {sorted(new)}: use .oc-btn (controls.css) instead"


def test_allowlist_has_no_stale_entries() -> None:
    gone = ALLOWED - shipped_button_bases()
    assert not gone, f"remove from ALLOWED, no longer defined: {sorted(gone)}"


def test_negative_control_a_new_family_is_flagged() -> None:
    assert button_bases(".shiny-new-btn { color: red }") - ALLOWED == {"shiny-new-btn"}


def test_no_new_widened_family() -> None:
    new = widened_families() - KNOWN_WIDENED
    assert not new, f"new button family {sorted(new)} (a button element with a state look): use the base Button (.oc-btn)"


def test_widened_known_list_has_no_stale_entries() -> None:
    gone = KNOWN_WIDENED - widened_families()
    assert not gone, f"remove from KNOWN_WIDENED, no longer defined: {sorted(gone)}"


def test_negative_control_widened_gate_sees_what_the_name_match_cannot() -> None:
    planted = "button.quiet-chip:hover { color: red } [role=button].row-pick[aria-pressed='true'] { color: red }"
    assert button_bases(planted) == set()
    assert stateful_button_bases(planted) == {"quiet-chip", "row-pick"}
    assert stateful_button_bases("button.plain-reset { margin: 0 } button.x--mod:hover {}") == set()


def test_planted_family_in_a_new_root_is_flagged(tmp_path, monkeypatch) -> None:
    root = tmp_path / "hosted"
    root.mkdir()
    (root / "page.css").write_text("button.sneaky-pick:hover { color: red }")
    monkeypatch.setattr(sys.modules[__name__], "REPO", tmp_path)
    assert widened_families() == {"sneaky-pick"}

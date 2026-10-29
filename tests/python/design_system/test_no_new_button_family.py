from __future__ import annotations

import re

from tests.python.design_system._sources import REPO, css_of

ALLOWED = frozenset({
    "adopt-attach-btn", "auth-button",
    "btn-icon", "command-button", "command-button-desc",
    "command-button-name", "folder-picker-navbtn",
    "folder-picker-toolbar-btn", "modal-btn", "modal-btn-alert",
    "modal-btn-confirm", "modal-btn-danger", "modal-btn-primary",
    "modal-btn-secondary", "oc-btn", "snd-btn",
    "oc-ibtn",
})
_CLASS = re.compile(r"\.([A-Za-z][\w-]*)")


def button_bases(css: str) -> set[str]:
    found: set[str] = set()
    for selector in re.findall(r"([^{}]+)\{", css):
        for name in _CLASS.findall(selector):
            if re.search(r"btn|button", name) and "__" not in name and "--" not in name:
                found.add(name)
    return found


def shipped_button_bases() -> set[str]:
    found: set[str] = set()
    for root in (REPO / "client" / "css", REPO / "web" / "src"):
        for path in root.rglob("*"):
            if path.is_file() and "node_modules" not in path.parts:
                found |= button_bases(css_of(path))
    return found


def test_no_new_button_family() -> None:
    new = shipped_button_bases() - ALLOWED
    assert not new, f"new button family {sorted(new)}: use .oc-btn (controls.css) instead"


def test_allowlist_has_no_stale_entries() -> None:
    gone = ALLOWED - shipped_button_bases()
    assert not gone, f"remove from ALLOWED, no longer defined: {sorted(gone)}"


def test_negative_control_a_new_family_is_flagged() -> None:
    assert button_bases(".shiny-new-btn { color: red }") - ALLOWED == {"shiny-new-btn"}

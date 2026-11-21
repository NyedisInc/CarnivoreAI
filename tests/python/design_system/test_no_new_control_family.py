from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from tests.python.design_system import test_no_new_button_family as buttons

KIND_WORDS: dict[str, frozenset[str]] = {
    "button": frozenset({"btn", "button"}),
    "field": frozenset({"input", "field", "select", "textarea"}),
    "tab": frozenset({"tab", "tabs", "tablist"}),
    "card": frozenset({"card"}),
}
_SELECTOR = re.compile(r"([^{}]+)\{")
_WORD_SPLIT = re.compile(r"__|-")

KNOWN_ELEMENT_BUTTONS = frozenset({
    "catalog-card__btn", "cbk__btn", "home-bar__btn", "info-tip__btn", "paste-fallback__btn", "sbr-rail__btn",
    "sidebar-help__nav-btn", "tlx-key__btn", "toast__thumb-btn",
})
KNOWN_FIELD_FAMILIES = frozenset({
    "acct__input", "admin-field", "ai-pick__input", "ap-diff__field", "ap-input", "auth-input", "auto-sched__field", "bar__input",
    "card-image__file-input", "cat-try__field", "cat-try__input", "cmp-field", "cmp-packname__field", "command-filter-input",
    "d-field", "dst-field", "dwl-field", "fdh-input", "hd-add-input", "hdc-input", "hdg-input", "hdq-input", "hds-field",
    "hdt-input", "header-rename-input", "hfk-field", "hse-field", "icp__input", "lcb__input", "lp-field", "lpm-field",
    "lsk-sheet__field", "mk2-field", "modal-input", "oc-facet__select", "oc-field", "oc-form-field", "oc-inline-field",
    "oc-inline-field__input", "oc-inline-field__select", "oc-lv-field", "oc-notes-field", "oc-pick__input", "oc-sf-field",
    "oc-split__select", "one-shot__field", "one-shot__select", "paste-fallback__input", "pm-field", "provider-add-input",
    "rbl-field", "rep__field", "sbb-select", "sbp-field", "session-sidebar-rename-input", "settings-field",
    "settings-wrapper-script-input", "sf__input", "share-select", "sheet__field", "sheet__select", "skp-input", "sp-field",
    "st-nav__select", "terminal-search__input", "tkm-note-input", "tkm-title-input", "tm__field", "tnf-field",
    "xterm-helper-textarea",
})
KNOWN_TAB_FAMILIES = frozenset({
    "ak-tabs", "ap-pn-tabs", "ap-tab", "ap-tabs", "ccp-tab", "ccp-tabs", "d-tabs", "had-tab", "had-tabs", "lcb__tabs",
    "oc-page__tabs", "oc-tab", "oc-tabs", "oc-task__tabs", "pk-tab", "plp-tabs", "ps-phone-tabs", "scc-tabs",
    "sg-page-tabs", "sk-tabs", "st-tabs", "wik__tabs",
})
KNOWN_CARD_FAMILIES = frozenset({
    "ap-card", "card", "cat-packs__card", "catalog-card", "d-card", "dash-card", "flw-card", "hdc-card", "hdf-card",
    "launchpad-error-card", "le-row__card", "m1-card", "mgr-card", "mk2-xt-card", "mw-card", "oc-card", "pot-card", "qc-card",
    "sw-card", "terminal-empty__card", "wp-card", "ww-card",
})
LISTS: dict[str, frozenset[str]] = {
    "button": KNOWN_ELEMENT_BUTTONS, "field": KNOWN_FIELD_FAMILIES, "tab": KNOWN_TAB_FAMILIES, "card": KNOWN_CARD_FAMILIES,
}
FLOOR = 5


def family_kind(name: str) -> str | None:
    last = _WORD_SPLIT.split(name.split("--")[0])[-1]
    return next((kind for kind, words in KIND_WORDS.items() if last in words), None)


def control_families(css: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {kind: set() for kind in KIND_WORDS}
    for selector in _SELECTOR.findall(css):
        for name in buttons._CLASS.findall(selector):
            kind = family_kind(name)
            if kind:
                found[kind].add(name.split("--")[0])
    return found


def shipped_families() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {kind: set() for kind in KIND_WORDS}
    for css in buttons._shipped_css(buttons.SCAN_ROOTS):
        for kind, names in control_families(css).items():
            found[kind] |= names
    found["button"] = {n for n in found["button"] if "__" in n} - buttons.ALLOWED - buttons.KNOWN_WIDENED
    return found


@pytest.mark.parametrize("kind", sorted(LISTS))
def test_no_new_control_family(kind: str) -> None:
    new = shipped_families()[kind] - LISTS[kind]
    assert not new, f"new {kind} family {sorted(new)}: use the base control (Button, the base fields, Tabs, the base card)"


@pytest.mark.parametrize("kind", sorted(LISTS))
def test_control_family_lists_have_no_stale_rows(kind: str) -> None:
    gone = LISTS[kind] - shipped_families()[kind]
    assert not gone, f"remove from the {kind} list, no longer defined: {sorted(gone)}"
    assert len(shipped_families()[kind]) >= FLOOR, f"the {kind} scan found almost nothing: it read the wrong tree"


def test_negative_control_each_kind_is_flagged_and_look_alikes_are_not() -> None:
    planted = ".zz__btn:hover {} .zz-input {} .zz-tabs--on {} .zz-card {} .zz-card__title {} .zz-btn-row {} .zz-tablet {}"
    assert control_families(planted) == {"button": {"zz__btn"}, "field": {"zz-input"}, "tab": {"zz-tabs"}, "card": {"zz-card"}}


def test_planted_families_in_a_scanned_root_are_flagged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for root in buttons.SCAN_ROOTS:
        (tmp_path / root).mkdir(parents=True)
    (tmp_path / "hosted" / "page.css").write_text(".sneaky__btn {} .sneaky-field {} .sneaky-tabs {} .sneaky-card {}")
    monkeypatch.setattr(sys.modules[buttons.__name__], "REPO", tmp_path)
    assert shipped_families() == {
        "button": {"sneaky__btn"}, "field": {"sneaky-field"}, "tab": {"sneaky-tabs"}, "card": {"sneaky-card"}}


def test_a_missing_root_is_never_a_clean_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.modules[buttons.__name__], "REPO", tmp_path)
    with pytest.raises(FileNotFoundError):
        shipped_families()

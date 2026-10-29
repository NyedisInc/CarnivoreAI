from __future__ import annotations

import re
from pathlib import Path
import pytest

from tests.python.design_system._sources import (
    ANY_PX, COLOUR, REPO, css_of, on_scale_literals, top_level_chunks, unlayered_rules,
)

SRC = REPO / "web" / "src"
SCOPE_DIRS = (
    "opscenter", "lib/terminal-search", "lib/session-control", "lib/terminal-foot-bar",
    "lib/terminal-empty", "lib/terminal-notice", "lib/terminal-background",
)
CSS_FILES = ("lib/session-control/control-center.css",)
COLOUR_LITERALS = {"lib/terminal-search/SearchPanel.svelte": 6}
UNLAYERED = {
    "opscenter/cells/notes/Cell.svelte": 4,
    "opscenter/cells/running-sessions/Cell.svelte": 16,
    "opscenter/cells/terminal-live/Cell.svelte": 4,
    "opscenter/layout-editor/WidgetDrawer.svelte": 18,
    "opscenter/layout-editor/DrawerHead.svelte": 3,
    "opscenter/layout-editor/DrawerTools.svelte": 3,
    "opscenter/shell/CellFrame.svelte": 2,
    "lib/session-control/control-center.css": 0,
    "lib/terminal-search/SearchPanel.svelte": 0,
    "lib/terminal-background/TerminalBackgroundButton.svelte": 0,
}
LEGACY_OVERRIDES: dict[str, dict[str, tuple[str, ...]]] = {
    "opscenter/cells/analytics/DetailsModal.svelte": {
        ":global(.text-prompt-modal.analytics-modal .modal-content)": ("display", "flex-direction", "box-sizing", "width", "max-width", "max-height"),
        ":global(.text-prompt-modal.analytics-modal .modal-body)": ("flex", "min-height", "overflow-x", "overflow-y", "overscroll-behavior", "padding"),
        ":global(.text-prompt-modal.analytics-modal .modal-footer)": ("flex", "box-shadow", "padding"),
        "@media (max-width: 600px) :global(.text-prompt-modal.analytics-modal .modal-content)": ("width", "height", "max-height", "border", "border-radius"),
    },
    "opscenter/layout-editor/BoardTransfer.svelte": {
        ".bt-row :global([data-btn])": ("flex", "min-height", "padding", "font-size"),
    },
}
LITERAL_BASELINE = 264
_ANY_PX = ANY_PX
_COLOUR = COLOUR


def styled_components() -> dict[str, str]:
    found: dict[str, str] = {}
    for scope in SCOPE_DIRS:
        for path in sorted((SRC / scope).rglob("*")):
            rel = str(path.relative_to(SRC))
            if "fixtures" in path.parts or not (path.suffix == ".svelte" or rel in CSS_FILES):
                continue
            css = css_of(path)
            if css.strip():
                found[rel] = css
    return found


def override_signatures(css: str) -> dict[str, tuple[str, ...]]:
    found: dict[str, tuple[str, ...]] = {}
    for chunk in top_level_chunks(css):
        if chunk.startswith("@layer"):
            continue
        selector, body = chunk.split("{", 1)
        selector = selector.strip()
        rules = top_level_chunks(body[:-1]) if selector.startswith("@media") else [chunk]
        for rule in rules:
            inner_selector, inner_body = rule.split("{", 1)
            name = (selector + " " if rules != [chunk] else "") + inner_selector.strip()
            found[name] = tuple(re.findall(r"(?:^|;)\s*([\w-]+)\s*:", inner_body[:-1]))
    return found


def permitted_unlayered(rel: str, css: str) -> int:
    expected = LEGACY_OVERRIDES.get(rel)
    if expected is None:
        return 0
    actual = override_signatures(css)
    assert actual == expected, f"legacy override drift in {rel}: {actual}"
    return len(expected)


def test_unlayered_rules_only_fall() -> None:
    bad = {}
    for rel, css in styled_components().items():
        n = unlayered_rules(css)
        n -= permitted_unlayered(rel, css)
        if n > UNLAYERED.get(rel, 0):
            bad[rel] = n
    assert not bad, f"rules outside @layer (wrap them in `@layer components`): {bad}"


def test_unlayered_list_has_no_stale_numbers() -> None:
    comps = styled_components()
    stale = {r: (n, unlayered_rules(comps[r])) for r, n in UNLAYERED.items() if r not in comps or unlayered_rules(comps[r]) < n}
    assert not stale, f"lower these UNLAYERED entries (allowed, actual): {stale}"


def test_on_scale_values_use_the_tokens() -> None:
    bad = {r: n for r, c in styled_components().items() if (n := on_scale_literals(c))}
    assert not bad, f"use --oc-space-* / --oc-fs-* for these on-scale px values: {bad}"


def test_off_scale_literals_only_fall() -> None:
    total = sum(len(_ANY_PX.findall(c)) for c in styled_components().values())
    assert total <= LITERAL_BASELINE, f"{total} literal spacing/type declarations, baseline {LITERAL_BASELINE}"


def test_no_colour_literals_in_component_styles() -> None:
    found = {r: len(_COLOUR.findall(c)) for r, c in styled_components().items() if _COLOUR.search(c)}
    bad = {r: n for r, n in found.items() if n > COLOUR_LITERALS.get(r, 0)}
    assert not bad, f"colour literals (use --oc-* tokens; tokens.css owns them): {bad}"


def test_negative_controls() -> None:
    assert unlayered_rules(".a { color: red } @layer components { .b { } }") == 1
    assert unlayered_rules("@layer components { .b { } }") == 0
    assert on_scale_literals(".x { padding: 0 8px; }") == 1
    assert on_scale_literals(".x { padding: 0 var(--oc-space-2); font-size: 13px }") == 0
    assert on_scale_literals(".x { font-size: 11px }") == 1
    assert _COLOUR.search(".x { color: #3f4649 }")
    with pytest.raises(AssertionError):
        permitted_unlayered("opscenter/layout-editor/BoardTransfer.svelte", ".bt-row :global([data-btn]) { flex: 1; min-height: 32px; padding: 0; font-size: 12px; color: red; }")
    with pytest.raises(AssertionError):
        permitted_unlayered("opscenter/layout-editor/BoardTransfer.svelte", ".bt-row :global([data-btn]) { flex: 1; min-height: 32px; padding: 0; font-size: 12px; } .new-rule { color: red; }")

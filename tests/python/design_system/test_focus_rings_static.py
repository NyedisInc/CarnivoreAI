
from __future__ import annotations

import re

import pytest

from tests.python.design_system._sources import REPO, css_of

CLIENT = REPO / "client"
FOCUS_ROOTS = (REPO / "client" / "css", REPO / "web" / "src")
SHARED_FOCUS = "web/src/opscenter/focus.css"
MIN_SHEETS = 500

RINGED = [
    ("session-row-menu.css", ".session-row-menu__item:focus-visible"),
    ("session-sidebar-density.css", ".session-sidebar-row:focus-visible"),
    ("config-editor.css", ".config-editor-file:focus-visible"),
    ("config-editor.css", ".config-editor-toggle:focus-visible"),
    ("home-bar.css", ".home-bar__btn:focus-visible"),
    ("home-bar.css", ".home-bar__link:focus-visible"),
]
RING = re.compile(r"box-shadow:\s*(?:inset\s+)?0\s+0\s+0\s+\d+px\s+var\(--(?:oc-orange|color-accent)\)")
_RULE = re.compile(r"([^{};]+)\{([^{}]*)\}")
_PAINT = re.compile(r"(?:^|;|\{)\s*(outline(?:-color)?|border(?:-(?:top|right|bottom|left))?(?:-color)?|box-shadow)\s*:\s*([^;}]*)")
_NO_PAINT = re.compile(r"(?:none|0|0px|transparent)(?:\s*!important)?")

FOCUS_PAINT_KNOWN: dict[str, int] = {
    "client/css/config-editor-modal.css": 1,
    "client/css/copy-output.css": 3,
    "client/css/new-agent-flow.css": 1,
    "client/css/paste-fallback.css": 2,
    "client/css/session-sidebar-rows.css": 1,
    "client/css/sidebar-help.css": 2,
    "client/css/styles.css": 6,
    "client/css/text-prompt-modal.css": 1,
    "web/src/lib/automations/auto-list.css": 1,
    "web/src/lib/automations/feed/feed.css": 1,
    "web/src/lib/automations/scheduled-tree.css": 1,
    "web/src/lib/browser/BrowserView.svelte": 1,
    "web/src/lib/catalog/AddSplit.svelte": 1,
    "web/src/lib/catalog/CatalogCard.svelte": 1,
    "web/src/lib/catalog/warez-card.css": 1,
    "web/src/lib/crosstalk/terminal-cards/terminal-cards.css": 1,
    "web/src/lib/dynamic-tabs/WidgetAreaBar.svelte": 1,
    "web/src/lib/elite/elite-board.css": 1,
    "web/src/lib/elite/elite-rail.css": 3,
    "web/src/lib/elite/elite.css": 5,
    "web/src/lib/file-drawer/FileDrawerGit.svelte": 1,
    "web/src/lib/file-drawer/FileDrawerHeader.svelte": 1,
    "web/src/lib/icon-picker/icon-picker.css": 1,
    "web/src/lib/pack-roster/roster.css": 1,
    "web/src/lib/project-colors/ProjectColorPopover.svelte": 1,
    "web/src/lib/sessions-page/sessions-list.css": 1,
    "web/src/lib/sessions-page/timeline.css": 4,
    "web/src/lib/terminal-background/TerminalBackgroundButton.svelte": 1,
    "web/src/lib/terminal-search/PromptTick.svelte": 1,
    "web/src/lib/terminal-search/SearchPanel.svelte": 1,
    "web/src/lib/widget-bars/BarEdge.svelte": 2,
    "web/src/lib/widgets-page/widgets-page.css": 2,
    "web/src/opscenter/cells/terminal-live/GitDiffView.svelte": 1,
    "web/src/opscenter/cells/terminal-live/SizeMasterCrown.svelte": 1,
    "web/src/opscenter/cells/terminal-live/TerminalActions.svelte": 1,
    "web/src/opscenter/dashgrid/dashgrid.css": 1,
}


def focus_rings(css: str, selector: str) -> list[str]:
    out = []
    for match in _RULE.finditer(css):
        if selector in match.group(1) and RING.search(match.group(2)):
            out.append(match.group(2).strip())
    return out


def focus_paints(css: str) -> int:
    count = 0
    for match in _RULE.finditer(css):
        if ":focus" in match.group(1):
            count += sum(1 for paint in _PAINT.finditer("{" + match.group(2)) if not _NO_PAINT.fullmatch(paint.group(2).strip()))
    return count


def focus_paint_counts() -> tuple[int, dict[str, int]]:
    scanned, found = 0, {}
    for root in FOCUS_ROOTS:
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(REPO).as_posix()
            if path.suffix not in (".css", ".svelte") or rel == SHARED_FOCUS:
                continue
            scanned += 1
            if (n := focus_paints(css_of(path))) > 0:
                found[rel] = n
    return scanned, found


def test_ring_scan_can_go_red() -> None:
    sample = ".x:focus-visible { box-shadow: inset 0 0 0 2px var(--oc-orange); }"
    assert focus_rings(sample, ".x:focus-visible")


@pytest.mark.parametrize(("sheet", "selector"), RINGED)
def test_no_own_focus_ring(sheet: str, selector: str) -> None:
    assert focus_rings(css_of(CLIENT / "css" / sheet), selector) == []


@pytest.mark.parametrize(
    ("sheet", "base"),
    [
        ("session-row-menu.css", ".session-row-menu .session-row-menu__item {"),
        ("config-editor.css", ".config-editor-file {"),
        ("home-bar.css", ".home-bar__link {"),
    ],
)
def test_reserved_transparent_border(sheet: str, base: str) -> None:
    css = css_of(CLIENT / "css" / sheet)
    block = css[css.index("\n" + base):].split("}", 1)[0]
    assert "border: 1px solid transparent" in block, f"{sheet} {base} lost its reserved border"


def test_focus_paint_scan_can_go_red() -> None:
    planted = (
        "@layer components { .a:focus-visible { outline: 2px solid var(--oc-cyan); border-color: red; box-shadow: none } }"
        ".b:focus { border: 1px solid var(--oc-orange) } .c:hover { outline: 1px solid red } .d:focus { outline: none }"
    )
    assert focus_paints(planted) == 3


def test_no_new_focus_paint_outside_the_shared_rule() -> None:
    scanned, found = focus_paint_counts()
    assert scanned >= MIN_SHEETS, f"only {scanned} sheets under {FOCUS_ROOTS}: the scan lost its subject"
    over = {rel: n for rel, n in found.items() if n > FOCUS_PAINT_KNOWN.get(rel, 0)}
    assert not over, f"focus is the shared rule's (web/src/opscenter/focus.css; tint with --_bd), not a per-component edge: {over}"
    stale = {rel: (n, found.get(rel, 0)) for rel, n in FOCUS_PAINT_KNOWN.items() if found.get(rel, 0) < n}
    assert not stale, f"lower or delete these FOCUS_PAINT_KNOWN rows (allowed, actual): {stale}"

from __future__ import annotations

from tests.python.design_system._sources import (
    ANY_PX, COLOUR, REPO, css_of, on_scale_literals, unlayered_rules,
)

SRC = REPO / "web" / "src"
SCOPE_DIRS = (
    "lib/drawer-tabs", "lib/drawer-zone", "lib/ledger-drawer", "lib/mini-rail",
    "lib/sidebar-shell", "lib/drawer",
)
LEGACY_SHEETS = (
    "client/css/session-sidebar.css",
    "client/css/session-sidebar-band-structure.css",
    "client/css/session-sidebar-colours.css",
    "client/css/session-sidebar-density.css",
    "client/css/session-sidebar-groups.css",
    "client/css/session-sidebar-keep-awake.css",
    "client/css/session-sidebar-account-chip.css",
    "client/css/session-sidebar-layouts.css",
    "client/css/session-sidebar-rail.css",
    "client/css/session-sidebar-resize.css",
    "client/css/session-sidebar-row-controls.css",
    "client/css/session-sidebar-rows.css",
    "client/css/version-footer.css",
    "client/css/session-row-menu.css",
)
UNLAYERED: dict[str, int] = {"client/css/version-footer.css": 4, "client/css/session-sidebar-rows.css": 3}
LITERAL_BASELINE = 94
PROVIDER_GLANCE = "web/src/lib/ledger-drawer/ProviderGlanceTile.svelte"
PROVIDER_GLANCE_LITERALS = {
    "padding: 3px 5px;": 1,
    "gap: 3px;": 1,
    "font-size: 9px;": 1,
    "padding: 0 1px;": 1,
}
COLOUR_LITERALS: dict[str, int] = {"client/css/session-sidebar-colours.css": 1}
RETIRED_CLASSES = ("mr-btn", "mr-btn--active")


def drawer_styles() -> dict[str, str]:
    found: dict[str, str] = {}
    for scope in SCOPE_DIRS:
        for path in sorted((SRC / scope).rglob("*.svelte")):
            css = css_of(path)
            if css.strip():
                found[str(path.relative_to(REPO))] = css
    for rel in LEGACY_SHEETS:
        path = REPO / rel
        assert path.is_file(), f"guarded sheet {rel} does not exist; fix LEGACY_SHEETS"
        found[rel] = css_of(path)
    return found


def test_unlayered_rules_only_fall() -> None:
    bad = {r: n for r, c in drawer_styles().items() if (n := unlayered_rules(c)) > UNLAYERED.get(r, 0)}
    assert not bad, f"rules outside @layer (wrap them in `@layer components`): {bad}"


def test_unlayered_list_has_no_stale_numbers() -> None:
    styles = drawer_styles()
    stale = {r: (n, unlayered_rules(styles[r])) for r, n in UNLAYERED.items() if r not in styles or unlayered_rules(styles[r]) < n}
    assert not stale, f"lower these UNLAYERED entries (allowed, actual): {stale}"


def test_on_scale_values_use_the_tokens() -> None:
    bad = {r: n for r, c in drawer_styles().items() if (n := on_scale_literals(c))}
    assert not bad, f"use --oc-space-* / --oc-fs-* for these on-scale px values: {bad}"


def test_off_scale_literals_only_fall() -> None:
    styles = drawer_styles()
    glance = styles[PROVIDER_GLANCE]
    assert {value: glance.count(value) for value in PROVIDER_GLANCE_LITERALS} == PROVIDER_GLANCE_LITERALS
    assert len(ANY_PX.findall(glance)) == sum(PROVIDER_GLANCE_LITERALS.values())
    total = sum(len(ANY_PX.findall(c)) for rel, c in styles.items() if rel != PROVIDER_GLANCE)
    assert total <= LITERAL_BASELINE, f"{total} literal spacing/type declarations, baseline {LITERAL_BASELINE}"


def test_no_colour_literals_in_drawer_styles() -> None:
    found = {r: len(COLOUR.findall(c)) for r, c in drawer_styles().items() if COLOUR.search(c)}
    bad = {r: n for r, n in found.items() if n > COLOUR_LITERALS.get(r, 0)}
    assert not bad, f"colour literals (use --oc-* tokens; tokens.css owns them): {bad}"


def test_retired_rail_button_class_stays_gone() -> None:
    bad = []
    for scope in SCOPE_DIRS:
        for path in (SRC / scope).rglob("*"):
            if path.suffix in {".svelte", ".ts"} and ".test." not in path.name:
                text = path.read_text()
                bad += [f"{path.name}: {c}" for c in RETIRED_CLASSES if f'"{c}' in text or f"'{c}" in text or f" {c}" in text]
    assert not bad, f"the rail's buttons are .oc-ibtn now: {bad}"


def test_negative_controls() -> None:
    assert unlayered_rules(".a { color: red } @layer components { .b { } }") == 1
    assert on_scale_literals(".x { padding: 0 8px; }") == 1
    assert on_scale_literals(".x { padding: 0 var(--oc-space-2); }") == 0
    assert COLOUR.search(".x { color: #3f4649 }")

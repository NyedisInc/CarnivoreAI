from __future__ import annotations

import re

from scripts.design import raw_controls as rc

COLUMN = "web/src/opscenter/cells/timeline/Column.svelte"
LEGEND = "web/src/opscenter/cells/analytics/ChartLegend.svelte"
TAB_KEY = "web/src/lib/zone-shell/TabKey.svelte"
TILE = "web/src/opscenter/cells/files/FilesGlanceTile.svelte"
EXPECTED: dict[str, dict[str, tuple[str, bool]]] = {
    COLUMN: {"tlc-sleep": ("quiet", True), "tlc-mark": ("quiet", True), "tlc-label": ("quiet", True)},
    LEGEND: {"chart-legend__item": ("quiet", True), "chart-legend__step": ("quiet", True)},
    TILE: {"fgl": ("secondary", True)},
}
_CLASS = re.compile(r'\bclass="([^"]*)"')


def button_tags(text: str) -> list[str]:
    blank = rc.blank_nonmarkup(text)
    return [blank[m.start():rc.tag_end(blank, m.start())] for m in re.finditer(r"<button(?=[\s/>])", blank)]


def problems(rel: str, text: str, expected: dict[str, tuple[str, bool]]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for tag in button_tags(text):
        match = _CLASS.search(tag)
        key = next((c for c in (match.group(1).split() if match else []) if c in expected), None)
        if key is None:
            found.append(f"{rel}: a button of no expected class: {tag[:60]}")
            continue
        seen.add(key)
        variant, ink = expected[key]
        if f"buttonAttrs('{variant}', 'bare')" not in tag:
            found.append(f"{rel}: {key} is not buttonAttrs('{variant}', 'bare')")
        if ink and 'data-focus="ink"' not in tag:
            found.append(f"{rel}: {key} has no data-focus=\"ink\"")
    found += [f"{rel}: no button of class {key}" for key in expected if key not in seen]
    return found


def _read(rel: str) -> str:
    return (rc.REPO / rel).read_text(encoding="utf-8")


def test_every_own_box_button_is_right_on_its_own_tag() -> None:
    assert not [p for rel, exp in EXPECTED.items() for p in problems(rel, _read(rel), exp)]


def test_the_tab_keys_close_key_is_bare_on_the_strip_and_the_files_hold_no_raw_button() -> None:
    text = _read(TAB_KEY)
    assert re.search(r"key: 'oc-tab-x', size: 'bare'", text) and "{...buttonAttrs('quiet', closeLook.size)}" in text
    assert not [rel for rel in (*EXPECTED, TAB_KEY) if rc.scan_text(_read(rel))[0].get("buttons")]


def test_the_base_owns_the_ink_focus_state() -> None:
    sheet = _read("web/src/lib/base/elements.css")
    assert re.search(r"\[data-btn\]\[data-focus='ink'\]\)\s*\{\s*--_btn-focus: currentColor;", sheet)
    assert 'data-focus="ink"' in _read("web/src/style-guide/specimens/BaseElements.svelte"), "a base state is shown in the style guide"
    assert 'data-focus="ink"' in _read("client/style-guide/sections/30b-base-elements.html")


def test_legend_buttons_reserve_a_transparent_edge_and_leave_the_cursor_to_the_base() -> None:
    text = _read(LEGEND)
    for rule in ("chart-legend__item {", "chart-legend__step {"):
        body = text[text.index(rule):].split("}", 1)[0]
        assert "solid transparent" in body and "margin: calc(var(--oc-border) * -1)" in body and "cursor" not in body, rule



def test_negative_control_sleep_without_ink_is_reported() -> None:
    text = _read(COLUMN).replace("class=\"tlc-sleep\" {...buttonAttrs('quiet', 'bare')} data-focus=\"ink\"", "class=\"tlc-sleep\" {...buttonAttrs('quiet', 'bare')}")
    assert text != _read(COLUMN) and problems(COLUMN, text, EXPECTED[COLUMN]) == [f"{COLUMN}: tlc-sleep has no data-focus=\"ink\""]


def test_negative_control_label_without_bare_is_reported() -> None:
    text = _read(COLUMN).replace("class=\"tlc-label\" {...buttonAttrs('quiet', 'bare')}", "class=\"tlc-label\" {...buttonAttrs('quiet', 'auto')}")
    assert text != _read(COLUMN) and problems(COLUMN, text, EXPECTED[COLUMN]) == [f"{COLUMN}: tlc-label is not buttonAttrs('quiet', 'bare')"]


def test_negative_control_one_stepper_without_bare_is_reported() -> None:
    text = _read(LEGEND)
    second = text.index('class="chart-legend__step"', text.index('class="chart-legend__step"') + 1)
    broken = text[:second] + text[second:].replace("buttonAttrs('quiet', 'bare')", "buttonAttrs('quiet', 'md')", 1)
    assert problems(LEGEND, broken, EXPECTED[LEGEND]) == [f"{LEGEND}: chart-legend__step is not buttonAttrs('quiet', 'bare')"]


def test_negative_control_a_raw_button_is_seen() -> None:
    assert rc.scan_text('<button type="button" class="x">go</button>')[0].get("buttons")

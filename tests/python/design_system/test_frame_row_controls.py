from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is not installed, so the frame row controls were NOT measured. Not a pass.")

from scripts.design import frame_header_controls as fhc  # noqa: E402
from scripts.design import raw_controls as rc  # noqa: E402
from tests.python.design_system.test_frame_tab_height import ENTRY, LAYERS, PAGES, SHELL, TAP, WEB, inline_css, sheet  # noqa: E402

_TAG = re.compile(r"<(IconButton|Button|FacetSelect|ViewToggle)(?=[\s/>])")
_ATTR = re.compile(r"""(?<![\w:-])([A-Za-z][\w:-]*)\s*=\s*"([^"{}]*)\"""")
FACET = '<label class="oc-facet oc-focus-host" data-ctl="{id}"><span class="oc-facet__key">sort</span><select class="oc-facet__select"><option>status</option></select></label>'
VIEW = (
    '<div class="oc-page__view" role="group">'
    '<button type="button" class="oc-ibtn" data-btn="secondary" data-size="icon" aria-pressed="true" data-ctl="{id}-grid">g</button>'
    '<button type="button" class="oc-ibtn" data-btn="secondary" data-size="icon" aria-pressed="false" data-ctl="{id}-list">l</button></div>'
)


def planted(name: str, tag: str, ctl: str) -> str:
    attrs = dict(_ATTR.findall(tag))
    hooks = " ".join(f'{k}="{v}"' for k, v in attrs.items() if k.startswith("data-") or k == "class")
    if name == "IconButton":
        kind = "secondary" if attrs.get("variant", "secondary") == "secondary" else "quiet"
        return f'<button type="button" data-btn="{kind}" data-size="icon" {hooks} data-ctl="{ctl}">i</button>'
    if name == "Button":
        return f'<button type="button" data-btn="{attrs.get("variant", "secondary")}" data-size="{attrs.get("size", "md")}" {hooks} data-ctl="{ctl}">go</button>'
    return (FACET if name == "FacetSelect" else VIEW).format(id=ctl)


def page_controls(rel: str) -> list[str]:
    path = WEB / rel
    source = path.read_text(encoding="utf-8")
    clean = rc.blank_nonmarkup(source)
    spans = fhc.header_snippet_spans(clean)
    texts = [clean[s:e] for s, e in spans] + [rc.blank_nonmarkup(p.read_text(encoding="utf-8")) for p in fhc.drawn_components(source, clean, spans, path)]
    out: list[str] = []
    for text in texts:
        for m in _TAG.finditer(text):
            out.append(planted(m.group(1), text[m.start():rc.tag_end(text, m.start())], f"c{len(out)}"))
    return out


def markup(page_class: str, controls: list[str]) -> str:
    own = "".join(controls)
    return (
        f'<div class="oc-page {page_class}" data-oc-base data-frame="column">'
        '<header class="oc-titlebar" data-frame-region="header" data-btn-density="frame"><h1 class="oc-titlebar__title">page</h1>'
        f'<div class="oc-titlebar__actions"><button type="button" data-btn="secondary" data-size="md" id="hb">go</button>'
        f'<span data-row="header">{own}</span></div></header>'
        '<div class="oc-page__away"><div class="oc-page__bar" data-frame-region="tools" data-btn-density="frame">'
        f'<div class="oc-toolbar" data-row="tools">{own}{FACET.format(id="kit-facet")}{VIEW.format(id="kit-view")}</div></div></div>'
        '<div class="oc-page__body" data-scroll="self" data-frame-region="body"><div class="oc-page__fill"></div></div></div>'
    )


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}); the frame row controls were NOT measured. Not a pass.")
        yield chromium
        chromium.close()


def measure(browser, name: str, width: int, coarse: bool) -> dict:
    page_class, sheets = PAGES[name][1], PAGES[name][4]
    css = LAYERS.read_text() + inline_css(ENTRY) + "".join(sheet(rel) for rel in sheets) + SHELL
    context = browser.new_context(viewport={"width": width, "height": 800}, has_touch=coarse)
    page = context.new_page()
    try:
        page.set_content(f"<!doctype html><html><head><style>{css}</style></head><body>{markup(page_class, page_controls(name))}</body></html>")
        return page.evaluate(
            """() => {
                const out = {coarse: matchMedia('(pointer: coarse)').matches, controls: {}, icons: []};
                out.hb = Math.round(document.getElementById('hb').getBoundingClientRect().height);
                document.querySelectorAll('[data-row] [data-ctl]').forEach((el) => {
                    const key = el.closest('[data-row]').dataset.row + ':' + el.dataset.ctl;
                    const r = el.getBoundingClientRect();
                    out.controls[key] = [Math.round(r.width), Math.round(r.height)];
                    if (el.dataset.size === 'icon') out.icons.push(key);
                });
                return out;
            }"""
        )
    finally:
        context.close()


def wrong(got: dict, h: int) -> dict:
    return {k: v for k, v in got["controls"].items() if v[1] != h or (k in got["icons"] and v[0] != h)}


def test_the_computers_page_hands_its_frame_its_real_controls() -> None:
    found = " ".join(page_controls("lib/pack-page/PackScreen.svelte"))
    assert 'data-roster-key="gear"' in found and 'data-act="add"' in found, found


def test_negative_control_a_page_rule_on_a_hook_goes_red(browser, tmp_path: Path) -> None:
    page_class, sheets = PAGES["lib/pack-page/PackScreen.svelte"][1], PAGES["lib/pack-page/PackScreen.svelte"][4]
    css = LAYERS.read_text() + inline_css(ENTRY) + "".join(sheet(rel) for rel in sheets) + SHELL + '[data-k="g"] { --oc-ibtn-size: 32px }'
    context = browser.new_context(viewport={"width": 1863, "height": 800})
    page = context.new_page()
    try:
        page.set_content(f"<!doctype html><html><head><style>{css}</style></head><body>{markup(page_class, [planted('IconButton', '<IconButton data-k=\"g\" />', 'g')])}</body></html>")
        h = page.evaluate("() => Math.round(document.querySelector('[data-row=header] [data-ctl=g]').getBoundingClientRect().height)")
    finally:
        context.close()
    assert h == 32, h
    assert wrong({"controls": {"g": [h, h]}, "icons": ["g"]}, 26), "the check must flag the planted 32px rule"


@pytest.mark.parametrize("name", sorted(PAGES))
@pytest.mark.parametrize("width", [1863, 900, 390])
def test_frame_row_controls_are_the_frame_height_under_a_mouse(browser, name: str, width: int) -> None:
    got = measure(browser, name, width, coarse=False)
    assert got["coarse"] is False and "tools:kit-facet" in got["controls"] and len(got["controls"]) >= 3, f"{name}: measured {got['controls']}"
    assert not wrong(got, got["hb"]), f"{name} at {width}: controls not {got['hb']}px like the header button: {wrong(got, got['hb'])}"


@pytest.mark.parametrize("name", sorted(PAGES))
def test_frame_row_controls_take_the_tap_size_under_a_touch_screen(browser, name: str) -> None:
    got = measure(browser, name, 1863, coarse=True)
    assert got["coarse"] is True and got["hb"] == TAP, f"{name}: header button {got['hb']}px"
    assert not wrong(got, TAP), f"{name}: controls not {TAP}px under a touch screen: {wrong(got, TAP)}"

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.python.design_system._sources import inline_css

pytest.importorskip("playwright.sync_api", reason="playwright is not installed, so the filter row was NOT measured. Not a pass.")

REPO = Path(__file__).resolve().parents[3]
ENTRY = REPO / "web" / "src" / "opscenter" / "app.css"
LAYERS = REPO / "client" / "css" / "layers.css"
PAGE_CSS = REPO / "web" / "src" / "lib" / "sessions-page" / "sessions-page.css"
FIT_BAR = REPO / "web" / "src" / "lib" / "sessions-page" / "fit-bar.ts"
ROLLDOWN = REPO / "web" / "node_modules" / ".bin" / "rolldown"
VIEWPORT = {"width": 1600, "height": 900}
WIDTHS = (1440, 1065, 900)
EPS = 0.5
OLD_FIXED_COMPACT_PX = 960
OLD_SHORT_PX = 40
SHELL = ":root { --overlay-top: 0px; } body { margin: 0; }"

SELECTS = {
    "company": ("any", "Intelligent Mobile Computing", "Ventures", "Personal"),
    "project": ("any", "Carnivore AI Development", "Cloude Code", "Warez"),
    "computer": ("any", "this computer", "mac-mini-m4-studio"),
    "provider": ("any", "claude code", "codex"),
    "sort": ("default", "name a to z", "last active"),
}


def _group(name: str, body: str) -> str:
    return f'<div class="sp-g" data-g="{name}"><span class="sp-gl">{name}</span>{body}</div>'


def _select(name: str) -> str:
    opts = "".join(f"<option>{o}</option>" for o in SELECTS[name])
    return f'<select data-field data-size="sm" aria-label="{name}" data-any="{SELECTS[name][0]}">{opts}</select>'


def bar_markup() -> str:
    state = "".join(
        f'<button type="button" data-btn data-variant="quiet" data-size="icon" data-state="{s}" aria-pressed="true" aria-label="{s}">'
        '<span style="display:inline-block;width:14px;height:14px"></span></button>'
        for s in ("working", "questions", "sleep", "closed", "archived")
    )
    facets = _group("state", f'<span class="sp-seg">{state}</span>') + "".join(_group(n, _select(n)) for n in SELECTS)
    views = "".join(
        f'<button type="button" role="radio" data-btn data-size="icon" data-view="{v}" aria-label="{v}"><span style="display:inline-block;width:14px;height:14px"></span></button>'
        for v in ("list", "pivot", "timeline")
    )
    end = (
        '<button type="button" data-btn data-size="sm" data-clear>clear</button>'
        f'<div class="oc-segmented" data-view-switch role="radiogroup">{views}</div><span class="sp-count">12 of 40</span>'
    )
    return (
        '<div class="sp-page"><div class="oc-toolbar oc-toolbar--band sp-bar" role="toolbar" id="bar">'
        f'<div class="oc-toolbar__facets">{facets}</div><div class="oc-toolbar__end">{end}</div></div></div>'
    )


@pytest.fixture(scope="module")
def fit_bar_js(tmp_path_factory) -> str:
    if not ROLLDOWN.exists():
        pytest.skip("rolldown is not installed under web/node_modules, so the filter row was NOT measured. Not a pass.")
    out = tmp_path_factory.mktemp("fitbar") / "fit-bar.js"
    done = subprocess.run(
        [str(ROLLDOWN), str(FIT_BAR), "--format=iife", "--name=FitBar", "--file", str(out)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert done.returncode == 0, done.stderr
    return out.read_text()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}); the filter row was NOT measured. Not a pass.")
        yield chromium
        chromium.close()


DRIVER = """() => {
    const bar = document.getElementById('bar');
    window.__stop = FitBar.watchBarFit(bar, (compact) => {
        bar.classList.toggle(FitBar.COMPACT_CLASS, compact);
        for (const sel of bar.querySelectorAll('select[data-any]')) {
            const any = sel.options[0];
            if (sel.closest('[data-g]').dataset.g !== 'sort') any.textContent = compact ? sel.getAttribute('aria-label') : sel.dataset.any;
        }
    });
}"""

MEASURE = """() => {
    const bar = document.getElementById('bar');
    const right = bar.getBoundingClientRect().right;
    const parts = [...bar.querySelectorAll('.sp-g, .oc-toolbar__end')].map((el) => ({
        part: el.dataset.g || 'end', over: Math.round((el.getBoundingClientRect().right - right) * 10) / 10 }));
    return { barW: bar.getBoundingClientRect().width, scrollW: bar.scrollWidth, clientW: bar.clientWidth, parts,
             compact: bar.classList.contains('sp-bar--compact'),
             lines: new Set([...bar.querySelectorAll('.sp-g')].map((el) => Math.round(el.getBoundingClientRect().top))).size };
}"""


def measure(browser, fit_bar_js: str, width: int) -> dict:
    context, page = _page(browser, fit_bar_js, width)
    try:
        return _settled(page)
    finally:
        context.close()


def _page(browser, fit_bar_js: str, width: int):
    css = LAYERS.read_text() + inline_css(ENTRY) + PAGE_CSS.read_text() + SHELL
    context = browser.new_context(viewport=VIEWPORT)
    page = context.new_page()
    page.set_content(
        f"<!doctype html><html><head><style>{css}</style></head><body>"
        f'<div id="clip" style="width:{width}px;overflow:hidden">{bar_markup()}</div></body></html>'
    )
    page.add_script_tag(content=fit_bar_js)
    page.evaluate(DRIVER)
    return context, page


def _settled(page) -> dict:
    page.wait_for_timeout(150)
    first = page.evaluate(MEASURE)
    page.wait_for_timeout(150)
    second = page.evaluate(MEASURE)
    assert first["compact"] == second["compact"], f"the compact state kept flipping: {first['compact']} then {second['compact']}"
    return second


@pytest.mark.parametrize("width", WIDTHS)
def test_row_stays_inside_its_bar(browser, fit_bar_js, width):
    got = measure(browser, fit_bar_js, width)
    assert got["barW"] == width, f"the planted bar is {got['barW']}px, not {width}px"
    spill = {p["part"]: p["over"] for p in got["parts"] if p["over"] > EPS}
    assert not spill, f"at {width}px a part runs past the bar's right edge (px over): {spill}; compact={got['compact']} lines={got['lines']}"
    assert got["scrollW"] <= got["clientW"], f"at {width}px the bar's content is {got['scrollW']}px in a {got['clientW']}px bar"


def test_roomy_form_kept_where_it_fits(browser, fit_bar_js):
    got = measure(browser, fit_bar_js, 1440)
    assert not got["compact"], "the 1440px bar dropped its labels although the labelled row fits"
    assert got["lines"] == 1, f"the 1440px bar wrapped its groups onto {got['lines']} lines"


def test_row_fits_just_under_the_labelled_facets(browser, fit_bar_js):
    context, page = _page(browser, fit_bar_js, 1500)
    try:
        _settled(page)
        wide = page.evaluate(
            """() => { const bar = document.getElementById('bar'); const f = bar.querySelector('.oc-toolbar__facets').getBoundingClientRect().width;
                       const s = getComputedStyle(bar); return f + parseFloat(s.paddingLeft) + parseFloat(s.paddingRight); }"""
        )
    finally:
        context.close()
    width = int(wide) - OLD_SHORT_PX
    assert width > OLD_FIXED_COMPACT_PX, f"the labelled facets ({wide}px with padding) are no wider than the old fixed rule, so this proves nothing"
    got = measure(browser, fit_bar_js, width)
    spill = {p["part"]: p["over"] for p in got["parts"] if p["over"] > EPS}
    assert not spill, f"at {width}px (labelled facets {wide}px) a part runs past the bar (px over): {spill}; compact={got['compact']}"
    assert got["scrollW"] <= got["clientW"]


def test_compact_has_hysteresis(browser, fit_bar_js):
    context, page = _page(browser, fit_bar_js, 1500)
    try:
        assert not _settled(page)["compact"]
        need = page.evaluate("FitBar.labelledNeed(document.getElementById('bar'))")
        margin = page.evaluate("FitBar.COMPACT_EXIT_MARGIN_PX")

        def at(width: float) -> bool:
            page.evaluate(f"document.getElementById('clip').style.width = '{width}px'")
            return _settled(page)["compact"]

        assert at(need - 2), "a bar 2px under the labelled need kept its labels"
        assert at(need + margin / 2), "a bar inside the exit margin left compact (it would flicker at the boundary)"
        assert not at(need + margin + 2), "a bar past the exit margin kept compact"
    finally:
        context.close()


def test_row_wraps_when_even_compact_does_not_fit(browser, fit_bar_js):
    context, page = _page(browser, fit_bar_js, 1500)
    try:
        _settled(page)
        page.evaluate("window.__stop()")
        compact_w = page.evaluate(
            """() => { const bar = document.getElementById('bar'); bar.classList.add(FitBar.COMPACT_CLASS);
                       const f = bar.querySelector('.oc-toolbar__facets').getBoundingClientRect().width; const s = getComputedStyle(bar);
                       return f + parseFloat(s.paddingLeft) + parseFloat(s.paddingRight); }"""
        )
    finally:
        context.close()
    width = int(compact_w) - OLD_SHORT_PX
    got = measure(browser, fit_bar_js, width)
    assert got["compact"], f"at {width}px the bar did not go compact, so the wrap was not the thing under test"
    spill = {p["part"]: p["over"] for p in got["parts"] if p["over"] > EPS}
    assert not spill, f"at {width}px (compact facets {compact_w}px) a part runs past the bar (px over): {spill}"
    assert got["scrollW"] <= got["clientW"]
    assert got["lines"] == 2, f"the groups sit on {got['lines']} lines at {width}px, not the two the wrap gives"

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is not installed, so the frame icon buttons were NOT measured. Not a pass.")

from tests.python.design_system.test_frame_tab_height import (  # noqa: E402
    LAYERS,
    PAGES,
    SHELL,
    TAP,
    ENTRY,
    inline_css,
    sheet,
)

MANAGER_SHEET = "lib/manager-frame/manager-frame.css"
TABLESS = {
    "lib/sessions-page/SessionsPage.svelte": ("sp-page", ("lib/sessions-page/sessions-page.css", "lib/sessions-page/sessions-panel.css"), "sp-acts"),
    "lib/catalog/CatalogScreen.svelte": (
        "cat",
        ("lib/catalog/CatalogScreen.svelte", "lib/catalog/WarezTools.svelte", "lib/catalog/catalog-phone-bar.css"),
        "wtools",
    ),
}
SUBJECTS = (
    {"lib/manager-frame/ManagerFrame.svelte": ("pledger mgr", (), "")}
    | {name: (spec[1], spec[4], "") for name, spec in PAGES.items()}
    | TABLESS
)

ICON = '<button type="button" class="oc-ibtn" data-btn="{kind}" data-size="icon" aria-label="x" id="{id}">i</button>'
VIEW = (
    '<div class="oc-page__view" role="group">'
    + ICON.format(kind="secondary", id="{p}-grid").replace('aria-label="x"', 'aria-pressed="true" aria-label="grid"')
    + ICON.format(kind="secondary", id="{p}-list").replace('aria-label="x"', 'aria-pressed="false" aria-label="list"')
    + "</div>"
)
FLIP = '<button type="button" class="oc-ibtn oc-page__flip" data-btn="secondary" data-size="icon" aria-label="flip" id="{p}-flip">i</button>'
REGIONS = ("header", "tabs", "bar", "detail")
ICONS_PER_REGION = 5
ICON_COUNT = len(REGIONS) * ICONS_PER_REGION


def region(p: str, wrapper: str = "") -> str:
    icons = ICON.format(kind="quiet", id=f"{p}-quiet") + ICON.format(kind="secondary", id=f"{p}-framed") + VIEW.format(p=p) + FLIP.format(p=p)
    return f'<div class="{wrapper}">{icons}</div>' if wrapper else icons


def markup(page_class: str, wrapper: str = "") -> str:
    return (
        f'<div class="oc-page {page_class}" data-oc-base data-frame="column">'
        '<header class="oc-titlebar" data-frame-region="header" data-btn-density="frame"><h1 class="oc-titlebar__title">page</h1>'
        f'<div class="oc-titlebar__actions"><button type="button" data-btn="secondary" data-size="md" id="hb">go</button>{region("header", wrapper)}</div></header>'
        '<div class="oc-page__away">'
        f'<div class="oc-page__tabs" data-frame-region="tabs" data-btn-density="frame">{region("tabs", wrapper)}</div>'
        f'<div class="oc-page__bar" data-frame-region="tools" data-btn-density="frame">{region("bar", wrapper)}</div></div>'
        '<div class="oc-page__body" data-scroll="self" data-frame-region="body"><div class="oc-page__fill">'
        f'<div id="outside">{VIEW.format(p="out")}</div></div>'
        '<aside class="oc-page__detail oc-page__detail--frame" data-frame-region="detail">'
        f'<div class="oc-page__detail-head" data-btn-density="frame"><h2 class="oc-page__detail-title">d</h2>'
        f'<div class="oc-page__detail-actions">{region("detail", wrapper)}</div></div></aside></div></div>'
    )


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}); the frame icon buttons were NOT measured. Not a pass.")
        yield chromium
        chromium.close()


def measure(browser, name: str, width: int, coarse: bool) -> dict:
    page_class, sheets, wrapper = SUBJECTS[name]
    css = LAYERS.read_text() + inline_css(ENTRY) + sheet(MANAGER_SHEET) + "".join(sheet(rel) for rel in sheets) + SHELL
    context = browser.new_context(viewport={"width": width, "height": 800}, has_touch=coarse)
    page = context.new_page()
    try:
        page.set_content(f"<!doctype html><html><head><style>{css}</style></head><body>{markup(page_class, wrapper)}</body></html>")
        return page.evaluate(
            """() => {
                const out = {coarse: matchMedia('(pointer: coarse)').matches};
                document.querySelectorAll('button').forEach((b) => {
                    const r = b.getBoundingClientRect();
                    out[b.id] = [Math.round(r.width), Math.round(r.height)];
                });
                return out;
            }"""
        )
    finally:
        context.close()


def icons(got: dict) -> dict:
    return {k: v for k, v in got.items() if k.split("-")[0] in REGIONS}


def test_negative_control_the_emulation_reports_the_pointer_it_was_asked_for(browser) -> None:
    name = next(iter(SUBJECTS))
    assert measure(browser, name, 1863, coarse=True)["coarse"] is True
    assert measure(browser, name, 1863, coarse=False)["coarse"] is False


@pytest.mark.parametrize("name", sorted(SUBJECTS))
@pytest.mark.parametrize("width", [1863, 900, 390])
def test_frame_region_icon_buttons_are_header_height_squares_under_a_mouse(browser, name: str, width: int) -> None:
    got = measure(browser, name, width, coarse=False)
    h = got["hb"][1]
    assert len(icons(got)) == ICON_COUNT, f"{name} at {width}: measured {len(icons(got))} icon buttons, expected {ICON_COUNT}"
    wrong = {k: v for k, v in icons(got).items() if v != [h, h]}
    assert not wrong, f"{name} at {width}: icon buttons not {h}x{h} like the header button: {wrong}"


@pytest.mark.parametrize("name", sorted(SUBJECTS))
def test_frame_region_icon_buttons_take_the_tap_size_under_a_touch_screen(browser, name: str) -> None:
    got = measure(browser, name, 1863, coarse=True)
    assert len(icons(got)) == ICON_COUNT, f"{name}: measured {len(icons(got))} icon buttons, expected {ICON_COUNT}"
    wrong = {k: v for k, v in icons(got).items() if v != [TAP, TAP]}
    assert not wrong and got["hb"][1] == TAP, f"{name}: header {got['hb']}, icon buttons not {TAP}x{TAP}: {wrong}"


def test_the_toggle_outside_a_frame_keeps_its_own_square(browser) -> None:
    got = measure(browser, "lib/manager-frame/ManagerFrame.svelte", 1863, coarse=False)
    assert got["out-grid"] == [24, 24] and got["out-list"] == [24, 24], got


PHONE_BAR_SHEETS = ("lib/catalog/CatalogPhoneBar.svelte", "lib/catalog/catalog-phone-bar.css", "lib/catalog/CatalogScreen.svelte")
PHONE_BAR = (
    '<div class="oc-page cat" data-oc-base data-frame="nav"><div class="catalog-phonebar">'
    '<div class="catalog-phonebar__row catalog-phonebar__row--tools" data-btn-density="frame">'
    '<button type="button" data-btn="secondary" data-size="sm" data-warez-act id="refresh">refresh</button>'
    '<div class="keys-menu"><button type="button" data-btn="secondary" data-size="icon" data-warez-act data-keys-button'
    ' aria-label="keys" id="keys">?</button></div></div></div></div>'
)


def measure_phone_bar(browser, coarse: bool) -> dict:
    css = LAYERS.read_text() + inline_css(ENTRY) + "".join(sheet(rel) for rel in PHONE_BAR_SHEETS) + SHELL
    context = browser.new_context(viewport={"width": 390, "height": 800}, has_touch=coarse)
    page = context.new_page()
    try:
        page.set_content(f"<!doctype html><html><head><style>{css}</style></head><body>{PHONE_BAR}</body></html>")
        return page.evaluate(
            """() => {
                const out = {coarse: matchMedia('(pointer: coarse)').matches};
                document.querySelectorAll('button').forEach((b) => {
                    const r = b.getBoundingClientRect();
                    out[b.id] = [Math.round(r.width), Math.round(r.height)];
                });
                return out;
            }"""
        )
    finally:
        context.close()


@pytest.mark.parametrize("coarse", [False, True])
def test_the_warez_phone_bar_keys_button_is_a_square_of_the_act_height(browser, coarse: bool) -> None:
    got = measure_phone_bar(browser, coarse)
    assert got["coarse"] is coarse
    h = TAP if coarse else got["refresh"][1]
    assert coarse or h < TAP, f"under a mouse the act should be the frame height, not the tap size: {got}"
    assert got["refresh"][1] == h and got["keys"] == [h, h], got

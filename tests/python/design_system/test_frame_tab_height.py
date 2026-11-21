from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is not installed, so the frame tabs were NOT measured. Not a pass.")

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "web" / "src"
ENTRY = WEB / "opscenter" / "app.css"
LAYERS = REPO / "client" / "css" / "layers.css"
_IMPORT = re.compile(r"""@import\s+(?:url\()?['"](\.[^'"]+)['"]\)?\s*;""")
_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
_GLOBAL = re.compile(r":global\(([^()]*)\)")
FRAME_H = 26
TAP = 44
SHELL = ":root { --overlay-top: 0px; } body { margin: 0; }"

PAGES = {
    "lib/automations/AutomationsScreen.svelte": (
        "column", "pledger ap-page", "ap-toptabs", "ap-tabrow", ("lib/automations/page.css", "lib/automations/pane/pane.css"),
    ),
    "lib/huddle-swarm/SwarmPage.svelte": ("column", "", "", "", ("lib/huddle-swarm/SwarmPage.svelte",)),
    "lib/pack-page/PackScreen.svelte": (
        "column", "pledger mgr pack-page", "", "", ("lib/pack-page/pack-page.css", "lib/pack-roster/roster.css"),
    ),
    "lib/settings-page/SettingsScreen.svelte": ("nav", "pledger mgr settings-page", "", "", ("lib/settings-page/settings-page.css",)),
    "lib/widgets-page/WidgetsScreen.svelte": ("nav", "wp-screen", "", "", ("lib/widgets-page/widgets-page.css",)),
}
_PAGE_TAG = re.compile(r"<Page\b((?:=>|[^>])*)>")


def inline_css(path: Path) -> str:
    return _IMPORT.sub(lambda m: inline_css((path.parent / m.group(1)).resolve()), path.read_text())


def sheet(rel: str) -> str:
    path = WEB / rel
    if path.suffix == ".svelte":
        return "\n".join(_GLOBAL.sub(r"\1", block) for block in _STYLE.findall(path.read_text()))
    return inline_css(path)


def framed_pages_with_tabs() -> set[str]:
    found = set()
    for path in WEB.rglob("*.svelte"):
        text = path.read_text()
        for tag in _PAGE_TAG.finditer(text):
            attrs = tag.group(1)
            if "frame=" in attrs and (re.search(r"\btabs=", attrs) or "{#snippet tabs()}" in text):
                found.add(path.relative_to(WEB).as_posix())
                break
    return found


def markup(frame: str, page_class: str, strip_class: str, wrapper: str) -> str:
    tabs = (
        f'<div class="oc-ptabs {strip_class}"><div class="oc-ptabs__list" role="tablist">'
        '<button type="button" class="oc-ptab" role="tab" aria-selected="true" id="t1"><span class="oc-ptab__label">one</span></button>'
        '<button type="button" class="oc-ptab" role="tab" aria-selected="false" id="t2"><span class="oc-ptab__label">two</span>'
        '<span class="oc-ptab__badge">3</span></button></div></div>'
    )
    if wrapper:
        tabs = f'<div class="{wrapper}">{tabs}</div>'
    rows = f'<div class="oc-page__away"><div class="oc-page__tabs" data-frame-region="tabs" data-btn-density="frame">{tabs}</div></div>'
    body = '<div class="oc-page__body" data-scroll="self" data-frame-region="body"><div class="oc-page__fill"></div></div>'
    inner = f'<div class="oc-page__frame" data-frame-region="frame"><div class="oc-page__col">{rows}{body}</div></div>' if frame == "nav" else rows + body
    return (
        f'<div class="oc-page {page_class}" data-oc-base data-frame="{frame}">'
        '<header class="oc-titlebar" data-frame-region="header" data-btn-density="frame"><h1 class="oc-titlebar__title">page</h1>'
        '<div class="oc-titlebar__actions"><button type="button" data-btn="secondary" data-size="md" id="hb">go</button></div></header>'
        f"{inner}</div>"
    )


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}); the frame tabs were NOT measured. Not a pass.")
        yield chromium
        chromium.close()


def measure(browser, name: str, width: int, coarse: bool, extra_css: str = "") -> dict:
    frame, page_class, strip_class, wrapper, sheets = BARE[name] if name in BARE else PAGES[name]
    css = LAYERS.read_text() + inline_css(ENTRY) + "".join(sheet(rel) for rel in sheets) + SHELL + extra_css
    context = browser.new_context(viewport={"width": width, "height": 800}, has_touch=coarse)
    page = context.new_page()
    try:
        page.set_content(f"<!doctype html><html><head><style>{css}</style></head><body>{markup(frame, page_class, strip_class, wrapper)}</body></html>")
        return page.evaluate(
            """() => {
                const h = (id) => Math.round(document.getElementById(id).getBoundingClientRect().height);
                const root = document.querySelector('.oc-page').getBoundingClientRect().left;
                const left = Math.round(document.getElementById('t1').getBoundingClientRect().left - root);
                return {coarse: matchMedia('(pointer: coarse)').matches, tabs: [h('t1'), h('t2')], header: h('hb'), left};
            }"""
        )
    finally:
        context.close()


SWARM = "lib/huddle-swarm/SwarmPage.svelte"

BARE = {"bare-column": ("column", "", "", "", ()), "planted-column": ("column", "x", "", "", ()), "bare-nav": ("nav", "", "", "", ())}
KNOWN_FIRST_TAB_OFFSETS: dict[str, str] = {}
KNOWN_UNMEASURED_STRIP_CLASSES = {
    "lib/settings-page/SettingsScreen.svelte": {"st-tabs": "the phone's own strip beside its section picker, not the frame's tab row"},
}
_TABS_TAG = re.compile(r"<Tabs\b((?:=>|[^>])*)>")
_CLASS_ATTR = re.compile(r"""\bclass=["']([^"']*)["']""")


def tabs_strip_classes(text: str) -> set[str]:
    found: set[str] = set()
    for tag in _TABS_TAG.finditer(text):
        for attr in _CLASS_ATTR.finditer(tag.group(1)):
            found.update(attr.group(1).split())
    return found


@pytest.mark.parametrize("name", sorted(PAGES))
def test_the_planted_strip_class_is_the_one_the_page_source_draws(name: str) -> None:
    want = set(PAGES[name][2].split())
    extra = set(KNOWN_UNMEASURED_STRIP_CLASSES.get(name, {}))
    got = tabs_strip_classes((WEB / name).read_text())
    assert got - extra == want, f"{name}: <Tabs> wears {sorted(got - extra)} in source, PAGES plants {sorted(want)}"
    assert extra <= got, f"{name}: stale KNOWN_UNMEASURED_STRIP_CLASSES row {sorted(extra - got)}"


def test_the_strip_class_check_goes_red_on_a_planted_class() -> None:
    assert tabs_strip_classes('<Tabs tabs={t} active={a}\n class="pk-tabs" />') == {"pk-tabs"}


def test_every_framed_page_with_tabs_is_measured() -> None:
    found = framed_pages_with_tabs()
    assert len(found) >= 4, f"the source scan found only {sorted(found)}; the scan is blind, not the pages gone"
    assert found == set(PAGES), f"framed pages with tabs not measured: {sorted(found - set(PAGES))}; listed but gone: {sorted(set(PAGES) - found)}"


def test_negative_control_the_emulation_reports_the_pointer_it_was_asked_for(browser) -> None:
    assert measure(browser, SWARM, 1863, coarse=True)["coarse"] is True
    assert measure(browser, SWARM, 1863, coarse=False)["coarse"] is False


@pytest.mark.parametrize("name", sorted(PAGES))
@pytest.mark.parametrize("width", [1863, 900, 600])
def test_a_framed_page_tabs_are_the_frame_height_under_a_mouse(browser, name: str, width: int) -> None:
    got = measure(browser, name, width, coarse=False)
    assert got["header"] == FRAME_H, f"{name} at {width}: the header button is {got['header']}px, not the frame's {FRAME_H}"
    assert got["tabs"] == [FRAME_H, FRAME_H], f"{name} at {width}: tabs {got['tabs']}px, the frame height is {FRAME_H}"


@pytest.mark.parametrize("name", sorted(PAGES))
def test_a_framed_page_tabs_take_the_tap_size_under_a_touch_screen(browser, name: str) -> None:
    got = measure(browser, name, 1863, coarse=True)
    assert got["tabs"] == [TAP, TAP] and got["header"] == TAP, f"{name}: {got}"


@pytest.mark.parametrize("name", sorted(PAGES))
def test_a_framed_page_first_tab_sits_where_the_frames_tab_row_puts_it(browser, name: str) -> None:
    want = measure(browser, "bare-" + PAGES[name][0], 1863, coarse=False)["left"]
    got = measure(browser, name, 1863, coarse=False)["left"]
    if name in KNOWN_FIRST_TAB_OFFSETS:
        assert got != want, f"{name} is on the frame's offset now ({want}px): delete it from KNOWN_FIRST_TAB_OFFSETS"
        return
    assert got == want, f"{name}: the first tab sits {got}px from the page edge, the frame's tab row puts it at {want}px"


def test_negative_control_the_offset_measure_sees_a_planted_gutter(browser) -> None:
    gutter = ".x .oc-ptabs { padding-inline: 16px }"
    bare = measure(browser, "bare-column", 1863, coarse=False)["left"]
    planted = measure(browser, "planted-column", 1863, coarse=False, extra_css=gutter)["left"]
    assert planted != bare, f"the planted gutter did not move the first tab ({planted}px vs the frame's {bare}px)"

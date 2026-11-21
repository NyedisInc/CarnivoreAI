from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is not installed, so the frame buttons were NOT measured. Not a pass.")

REPO = Path(__file__).resolve().parents[3]
ENTRY = REPO / "web" / "src" / "opscenter" / "app.css"
LAYERS = REPO / "client" / "css" / "layers.css"
_IMPORT = re.compile(r"""@import\s+(?:url\()?['"](\.[^'"]+)['"]\)?\s*;""")
FRAME_H = 26
TAP = 44

BUTTONS = (
    '<button type="button" data-btn="secondary" data-size="md" id="{p}-md">go</button>'
    '<button type="button" data-btn="secondary" data-size="sm" id="{p}-sm">go</button>'
    '<button type="button" data-btn="quiet" data-size="icon" id="{p}-icon" aria-label="x">i</button>'
)
MARKUP = (
    f'<div id="plain">{BUTTONS.format(p="plain")}</div>'
    f'<div class="oc-page oc-page--embedded" id="legacy"><header class="oc-titlebar"><span>{BUTTONS.format(p="legacy")}</span></header></div>'
    f'<div class="oc-page oc-page--embedded" id="framed" data-frame="column"><header class="oc-titlebar" data-btn-density="frame"><span>{BUTTONS.format(p="framed")}</span></header>'
    f'<div class="oc-page__bar" data-btn-density="frame"><span>{BUTTONS.format(p="bar")}</span></div></div>'
    f'<div class="oc-page oc-page--embedded" id="undeclared" data-frame="column"><header class="oc-titlebar"><span>{BUTTONS.format(p="undeclared")}</span></header></div>'
)


def inline_css(path: Path) -> str:
    text = path.read_text()
    return _IMPORT.sub(lambda m: inline_css((path.parent / m.group(1)).resolve()), text)


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}); the frame buttons were NOT measured. Not a pass.")
        yield chromium
        chromium.close()


def measure(browser, width: int, coarse: bool) -> dict:
    css = LAYERS.read_text() + inline_css(ENTRY)
    html = f"<!doctype html><html><head><style>{css}</style></head><body>{MARKUP}</body></html>"
    context = browser.new_context(viewport={"width": width, "height": 800}, has_touch=coarse, is_mobile=coarse)
    page = context.new_page()
    try:
        page.set_content(html)
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


def test_negative_control_the_emulation_reports_the_pointer_it_was_asked_for(browser) -> None:
    assert measure(browser, 1280, coarse=True)["coarse"] is True
    assert measure(browser, 1280, coarse=False)["coarse"] is False


@pytest.mark.parametrize(("width", "coarse"), [(1280, False), (600, False), (1280, True)])
def test_an_unframed_page_header_keeps_the_sizes_it_has_outside_a_page(browser, width: int, coarse: bool) -> None:
    got = measure(browser, width, coarse)
    for kind in ("md", "sm", "icon"):
        assert got[f"legacy-{kind}"] == got[f"plain-{kind}"], f"{kind}: {got[f'legacy-{kind}']} in an unframed header, {got[f'plain-{kind}']} outside"
    assert got["legacy-icon"][0] == got["legacy-icon"][1], "an icon button stays square"


def test_negative_control_a_region_that_does_not_declare_the_density_is_not_framed(browser) -> None:
    got = measure(browser, 1280, coarse=False)
    assert got["undeclared-md"] == got["plain-md"] and got["undeclared-md"][1] != FRAME_H


def test_the_frame_sheet_writes_no_button_size() -> None:
    text = re.sub(r"/\*.*?\*/", "", (REPO / "web" / "src" / "opscenter" / "page-frames.css").read_text(), flags=re.S)
    assert not re.search(r"--_btn-[\w-]*\s*:", text) and "[data-btn" not in text


@pytest.mark.parametrize("region", ["framed", "bar"])
def test_a_framed_page_buttons_are_the_frame_height_and_the_icon_is_square(browser, region: str) -> None:
    got = measure(browser, 1280, coarse=False)
    assert got[f"{region}-md"][1] == FRAME_H and got[f"{region}-sm"][1] == FRAME_H
    assert got[f"{region}-icon"] == [FRAME_H, FRAME_H]


def test_a_narrow_mouse_window_keeps_the_frame_height(browser) -> None:
    got = measure(browser, 600, coarse=False)
    assert got["framed-md"][1] == FRAME_H and got["framed-sm"][1] == FRAME_H
    assert got["framed-icon"] == [FRAME_H, FRAME_H]


@pytest.mark.parametrize("region", ["framed", "bar"])
def test_a_coarse_pointer_keeps_the_tap_floor(browser, region: str) -> None:
    got = measure(browser, 1280, coarse=True)
    assert got[f"{region}-md"][1] >= TAP and got[f"{region}-sm"][1] >= TAP
    assert got[f"{region}-icon"][1] >= TAP and got[f"{region}-icon"][0] == got[f"{region}-icon"][1]

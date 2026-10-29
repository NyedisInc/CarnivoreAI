from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip(
    "playwright.sync_api",
    reason="playwright is not installed, so the page layers were NOT measured. Not a pass.",
)

REPO = Path(__file__).resolve().parents[3]
APP_CSS = REPO / "client" / "dist" / "app.css"
THEMES = ("dracula", "carnivore-light")
TAB_THEMES = ("dracula", "carnivore-light", "matrix")

MARKUP = """
<div class="oc-page oc-page--embedded" id="outer">
  <header class="oc-titlebar" id="titlebar"><h1 class="oc-titlebar__title">skills</h1></header>
  <div class="oc-page__tabs"><div class="oc-ptabs"><div class="oc-ptabs__list">
    <button class="oc-ptab" aria-selected="true" id="tab-on">catalog</button>
    <button class="oc-ptab" aria-selected="false" id="tab-off">installed</button>
  </div></div></div>
  <div class="oc-page__bar" id="bar"><label class="oc-page__search">search</label></div>
  <div class="oc-page__body" id="body">
    <div class="oc-page oc-page--embedded oc-page--inset" id="inset">
      <div class="oc-page__bar" id="inset-bar">filters</div>
      <div class="oc-page__body" id="inset-body"><p>data</p></div>
    </div>
  </div>
</div>
<div id="probe-band"></div><div id="probe-content"></div><div id="probe-panel"></div>
"""


def theme_vars(theme: str) -> dict[str, str]:
    data = json.loads((REPO / "client" / "css" / "themes" / theme / "theme.json").read_text())
    return {k: v for k, v in data["cssVars"].items() if k.startswith("--")}


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    if not APP_CSS.exists():
        pytest.skip("client/dist/app.css is not built; run npm run build in web/. Not a pass.")
    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}); the layers were NOT measured. Not a pass.")
        yield chromium
        chromium.close()


def measure(browser, theme: str) -> dict[str, str]:
    variables = theme_vars(theme)
    root_style = "".join(f"{k}: {v};" for k, v in variables.items())
    html = (
        f"<!doctype html><html style=\"{root_style}\"><head><style>{APP_CSS.read_text()}</style>"
        "<style>#probe-band{background:var(--color-header-bg)}"
        "#probe-content{background:var(--color-bg-page)}"
        "#probe-panel{background:var(--color-bg)}</style></head>"
        f"<body>{MARKUP}</body></html>"
    )
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    try:
        page.set_content(html)
        return page.evaluate(
            """() => {
                const bg = (id) => getComputedStyle(document.getElementById(id)).backgroundColor;
                const out = {};
                for (const id of ['outer', 'titlebar', 'tab-on', 'tab-off', 'bar', 'inset', 'inset-bar',
                                  'probe-band', 'probe-content', 'probe-panel']) out[id] = bg(id);
                out.accent = getComputedStyle(document.documentElement).getPropertyValue('--color-accent').trim();
                return out;
            }"""
        )
    finally:
        page.close()


def test_the_two_themes_tell_the_grounds_apart(browser):
    dark, light = (measure(browser, t) for t in THEMES)
    assert dark["accent"] != light["accent"], "the two themes must have different accents"
    for got in (dark, light):
        assert got["probe-band"] != got["probe-content"], "a theme whose band equals its page proves nothing"
    assert dark["probe-panel"] != dark["probe-band"]
    assert light["probe-panel"] == light["probe-content"]


@pytest.mark.parametrize("theme", THEMES)
def test_band_holds_the_top_and_content_holds_the_data(browser, theme):
    got = measure(browser, theme)
    band, content = got["probe-band"], got["probe-content"]
    for region in ("titlebar", "bar", "inset-bar"):
        assert got[region] == band, f"{theme}: {region} is {got[region]}, the band is {band}"
    for region in ("outer", "inset"):
        assert got[region] == content, f"{theme}: {region} is {got[region]}, the content ground is {content}"


def luminance(color: str) -> float:
    import re

    srgb = re.fullmatch(r"color\(srgb ([\d.e+-]+) ([\d.e+-]+) ([\d.e+-]+)(?: / [\d.]+)?\)", color.strip())
    rgb = re.fullmatch(r"rgba?\((\d+), (\d+), (\d+)(?:, [\d.]+)?\)", color.strip())
    if srgb:
        channels = [float(v) for v in srgb.groups()]
    elif rgb:
        channels = [int(v) / 255 for v in rgb.groups()]
    else:
        raise ValueError(f"unreadable color {color!r}")
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def test_luminance_reads_both_serializations():
    assert luminance("rgb(0, 0, 0)") < luminance("color(srgb 0.5 0.5 0.5)") < luminance("rgb(255, 255, 255)")
    with pytest.raises(ValueError):
        luminance("transparent")


@pytest.mark.parametrize("theme", TAB_THEMES)
def test_the_selected_tab_is_lighter_than_an_unselected_one(browser, theme):
    got = measure(browser, theme)
    on, off = luminance(got["tab-on"]), luminance(got["tab-off"])
    assert on > off, f"{theme}: selected {got['tab-on']} is not lighter than unselected {got['tab-off']}"


WIDGET_MARKUP = """
<section class="oc-frame" id="frame" style="width:720px"><div class="oc-ptabs"><div class="oc-ptabs__list">
  <button class="oc-ptab" aria-selected="true" id="w-on">pipeline</button>
  <button class="oc-ptab" aria-selected="false" id="w-off">scheduled</button>
</div></div><div id="w-body" style="background:var(--oc-ground-panel);color:var(--oc-text-primary)">
  <table style="width:100%;border-collapse:collapse">
    <thead><tr><th>name</th><th>area</th><th>run time</th><th>ago</th><th>runs</th></tr></thead>
    <tbody>
      <tr><td>stats</td><td>fix login</td><td>120 ms</td><td>1m ago</td><td>5</td></tr>
      <tr><td>deep search</td><td>carnivore</td><td>240 ms</td><td>2m ago</td><td>6</td></tr>
      <tr><td>stats</td><td>machine</td><td>360 ms</td><td>3m ago</td><td>7</td></tr>
    </tbody>
  </table>
</div></section>
<div class="oc-page" id="embedded-page"><div class="oc-ptabs"><div class="oc-ptabs__list">
  <button class="oc-ptab" aria-selected="true" id="p-on">catalog</button>
  <button class="oc-ptab" aria-selected="false" id="p-off">installed</button>
</div></div></div>
<section class="oc-frame"><div class="oc-page"><div class="oc-ptabs"><div class="oc-ptabs__list">
  <button class="oc-ptab" aria-selected="true" id="fp-on">catalog</button>
</div></div></div></section>
<div class="oc-ptabs oc-ptabs--joined"><div class="oc-ptabs__list">
  <button class="oc-ptab" aria-selected="true" id="j-on">joined</button>
</div></div>
"""


def measure_widget(browser, theme: str) -> dict[str, str]:
    root_style = "".join(f"{k}: {v};" for k, v in theme_vars(theme).items())
    html = (
        f"<!doctype html><html style=\"{root_style}\"><head><style>{APP_CSS.read_text()}</style></head>"
        f"<body>{WIDGET_MARKUP}</body></html>"
    )
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    try:
        page.set_content(html)
        return page.evaluate(
            """() => {
                const cs = (id) => getComputedStyle(document.getElementById(id));
                const out = {};
                for (const id of ['w-on', 'w-off', 'w-body', 'p-on', 'p-off', 'fp-on', 'j-on'])
                    out[id] = cs(id).backgroundColor;
                out['w-on-shadow'] = cs('w-on').boxShadow;
                return out;
            }"""
        )
    finally:
        page.close()


@pytest.mark.parametrize("theme", TAB_THEMES)
def test_a_widget_tab_is_joined_to_its_body(browser, theme):
    got = measure_widget(browser, theme)
    assert got["w-on"] == got["w-body"], f"{theme}: widget tab {got['w-on']} != body {got['w-body']}"
    assert got["j-on"] == got["w-body"], f"{theme}: .oc-ptabs--joined {got['j-on']} != body {got['w-body']}"
    assert got["w-off"] != got["w-body"], f"{theme}: the unselected widget tab must stay a different fill"
    assert "-1px" not in got["w-on-shadow"], f"{theme}: a hairline under the picked tab: {got['w-on-shadow']}"


@pytest.mark.parametrize("theme", TAB_THEMES)
def test_full_page_tabs_keep_the_lighter_selected_fill(browser, theme):
    got = measure_widget(browser, theme)
    assert luminance(got["p-on"]) > luminance(got["p-off"]), f"{theme}: full-page selected is not lighter"
    flat = measure(browser, theme)
    assert got["p-on"] == flat["tab-on"], f"{theme}: full-page selected fill changed"
    assert got["fp-on"] == got["p-on"], f"{theme}: a page inside a frame must stay a full page"
    assert got["p-on"] != got["w-body"], f"{theme}: the full-page selected fill must not be the widget body ground"


JOINED_THEMES = ("dracula", "matrix", "carnivore", "carnivore-light")
MIN_STEP = 6.0
NEAR_BLACK = 8.0

PIXEL_READER = """async ([b64, points]) => {
    const img = await createImageBitmap(await (await fetch('data:image/png;base64,' + b64)).blob());
    const canvas = new OffscreenCanvas(img.width, img.height);
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const out = {};
    for (const [name, x, y] of points) out[name] = Array.from(ctx.getImageData(Math.round(x), Math.round(y), 1, 1).data.slice(0, 3));
    return out;
}"""


def luma(rgb: list[int]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def measure_painted(browser, theme: str) -> dict[str, list[int]]:
    root_style = "".join(f"{k}: {v};" for k, v in theme_vars(theme).items())
    html = (
        f"<!doctype html><html style=\"{root_style}\"><head><style>{APP_CSS.read_text()}</style></head>"
        f"<body style=\"margin:0;background:var(--oc-ground-page)\">{WIDGET_MARKUP}</body></html>"
    )
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    try:
        page.set_content(html)
        rects = page.evaluate(
            """() => {
                const r = (id) => { const b = document.getElementById(id).getBoundingClientRect();
                    return {l: b.left, t: b.top, w: b.width, b: b.bottom}; };
                const strip = document.querySelector('#frame .oc-ptabs').getBoundingClientRect();
                return {on: r('w-on'), off: r('w-off'), strip: {l: strip.left, t: strip.top, w: strip.width, b: strip.bottom}};
            }"""
        )
        on, off, strip = rects["on"], rects["off"], rects["strip"]
        mid = on["t"] + 16
        sel_x, off_x, strip_x = on["l"] + on["w"] - 8, off["l"] + off["w"] - 8, strip["l"] + strip["w"] - 20

        def points(suffix: str) -> list:
            return [
                ["sel" + suffix, sel_x, mid], ["body" + suffix, sel_x, on["b"] + 4],
                ["strip" + suffix, strip_x, mid], ["unsel" + suffix, off_x, mid],
                ["under_sel" + suffix, sel_x, on["b"] - 1], ["under_unsel" + suffix, off_x, off["b"] - 1],
                ["under_strip" + suffix, strip_x, strip["b"] - 1],
            ]

        import base64

        out = page.evaluate(PIXEL_READER, [base64.b64encode(page.screenshot()).decode(), points("")])
        page.mouse.move(off_x, mid)
        hovered = page.evaluate(PIXEL_READER, [base64.b64encode(page.screenshot()).decode(), [["hover", off_x, mid]]])
        return {**out, **hovered}
    finally:
        page.close()


def test_the_pixel_reader_can_go_red(browser):
    got = measure_painted(browser, "carnivore")
    assert abs(luma(got["body"]) - luma(got["strip"])) >= MIN_STEP
    assert got["sel"] != got["strip"], "the reader returned one color for everything"


@pytest.mark.parametrize("theme", JOINED_THEMES)
def test_a_widget_tab_reads_as_part_of_the_card_in_painted_pixels(browser, theme):
    got = measure_painted(browser, theme)
    assert got["sel"] == got["body"], f"{theme}: picked tab {got['sel']} != body {got['body']}"
    body, strip = luma(got["body"]), luma(got["strip"])
    assert abs(body - strip) >= MIN_STEP, f"{theme}: strip {got['strip']} is not a visible step from body {got['body']}"
    if body < NEAR_BLACK:
        assert strip > body, f"{theme}: a near-black body has nothing darker; the strip must step lighter"
    else:
        assert strip < body, f"{theme}: the strip {got['strip']} must be darker than the body {got['body']}"
    assert got["unsel"] == got["strip"], f"{theme}: other tab {got['unsel']} != strip {got['strip']}"
    assert got["under_sel"] == got["sel"], f"{theme}: a hairline under the picked tab: {got['under_sel']}"
    assert got["under_unsel"] != got["unsel"], f"{theme}: no hairline under the other tab"
    assert got["under_strip"] != got["strip"], f"{theme}: no hairline under the strip's empty space"
    assert abs(luma(got["hover"]) - body) < abs(luma(got["unsel"]) - body), f"{theme}: hover did not step toward the body"

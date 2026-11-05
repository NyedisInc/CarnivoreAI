from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is not installed, so the legend was NOT measured. Not a pass.")
from playwright.sync_api import Browser, Error as PlaywrightError, sync_playwright  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "web"
CONFIG = WEB / "vite.chart-legend-harness.config.ts"
THEMES = ("carnivore", "matrix")
WIDTHS = (1200, 400)
BREAK_CAP = "@layer components { .chart-legend__item { max-width: 100% !important; } }"
BREAK_ROOM = "@layer components { .chart-legend__view { margin: 0 !important; padding: 0 !important; } }"

MEASURE = """() => {
  const out = { cut: [], clipped: [], names: [], heights: {} };
  for (const key of ['single', 'wrap']) {
    const root = document.querySelector(`[data-rh="${key}"]`);
    const view = root.querySelector('.chart-legend__view').getBoundingClientRect();
    out.heights[key] = root.querySelector('.chart-legend').getBoundingClientRect().height;
    for (const cell of root.querySelectorAll('.chart-legend__cell:not(.chart-legend__cell--off)')) {
      const item = cell.querySelector('.chart-legend__item'); const span = item.querySelector('span'); const b = item.getBoundingClientRect();
      out.names.push([key, span.textContent, +span.getBoundingClientRect().width.toFixed(2)]);
      if (span.scrollWidth > span.clientWidth) out.cut.push(`${key}:${span.textContent}`);
      if (b.left < view.left - 0.01 || b.right > view.right + 0.01 || b.top < view.top - 0.01 || b.bottom > view.bottom + 0.01) out.clipped.push(`${key}:${span.textContent}`);
    }
  }
  return out;
}"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not (WEB / "node_modules").is_dir() or shutil.which("npx") is None:
        pytest.skip("web/node_modules or npx is missing, so the legend was NOT measured. Not a pass.")
    out = tmp_path_factory.mktemp("legend-harness")
    done = subprocess.run(["npx", "vite", "build", "--config", str(CONFIG)], cwd=WEB, env={**os.environ, "HARNESS_OUT": str(out)},
                          capture_output=True, text=True, timeout=300, check=False)
    assert done.returncode == 0 and (out / "harness.js").is_file(), f"the harness did not build:\n{done.stderr[-800:]}"
    return out


@pytest.fixture(scope="module")
def browser(harness: Path) -> Iterator[Browser]:
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except PlaywrightError as error:
            pytest.skip(f"chromium is unavailable ({error}), so the legend was NOT measured. Not a pass.")
        try:
            yield b
        finally:
            b.close()


def measure(browser: Browser, harness: Path, theme: str, width: int, extra_css: str = "") -> dict[str, Any]:
    cssvars = json.loads((REPO / "client" / "css" / "themes" / theme / "theme.json").read_text(encoding="utf-8"))["cssVars"]
    root_style = ";".join(f"{k}:{v}" for k, v in cssvars.items())
    layers = (REPO / "client" / "css" / "layers.css").read_text(encoding="utf-8")
    page = browser.new_page(viewport={"width": width, "height": 900})
    try:
        page.set_content(
            f'<!doctype html><html style="{root_style}"><head><meta charset="utf-8"><style>{layers}</style>'
            f'<style>{(harness / "harness.css").read_text(encoding="utf-8")}</style><style>{extra_css}</style></head>'
            '<body style="margin:12px;background:var(--oc-ground-page)"><section data-rh="single" style="width:min(520px,100%)"></section>'
            '<section data-rh="wrap" style="width:min(150px,100%);margin-top:12px"></section>'
            f"<script type=module>{(harness / 'harness.js').read_text(encoding='utf-8')}</script></body></html>")
        page.wait_for_function('document.documentElement.dataset.rhReady === "1"')
        page.wait_for_timeout(400)
        return page.evaluate(MEASURE)
    finally:
        page.close()


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("theme", THEMES)
def test_no_legend_name_is_cut_and_no_edge_is_clipped(browser: Browser, harness: Path, theme: str, width: int) -> None:
    got = measure(browser, harness, theme, width)
    assert len(got["names"]) >= 6, f"the legend rendered too few names to prove anything: {got['names']}"
    assert not got["cut"], f"legend names are cut off with an ellipsis: {got['cut']}"
    assert not got["clipped"], f"legend focus edges lie outside the clip: {got['clipped']}"


@pytest.mark.parametrize("theme", THEMES)
def test_negative_control_a_capped_item_is_reported_as_cut(browser: Browser, harness: Path, theme: str) -> None:
    assert measure(browser, harness, theme, 1200, BREAK_CAP)["cut"], "the cut-name check cannot go red"


@pytest.mark.parametrize("theme", THEMES)
def test_negative_control_removed_clip_room_is_reported_as_clipped(browser: Browser, harness: Path, theme: str) -> None:
    assert measure(browser, harness, theme, 1200, BREAK_ROOM)["clipped"], "the clip check cannot go red"

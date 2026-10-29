from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip(
    "playwright",
    reason="playwright is not installed, so NOTHING about the automations layout was measured. A could-not-evaluate, not a pass.",
)

from playwright._impl._driver import compute_driver_executable  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
CLIENT_ROOT = REPO_ROOT / "client"
PROBE = Path(__file__).resolve().parent / "automations_layout_probe.mjs"

WIDTHS = (600, 900, 1132, 1400)
DOCK_FROM = 900
PANE_MAX = 760
TITLE_ONE_ROW_MAX = 48
TREE_NAME_MIN = 150
SLACK = 1.5


def _probe(theme: str) -> list[dict]:
    node, cli = compute_driver_executable()
    package = Path(cli).parent
    if not Path(node).exists() or not package.is_dir():
        pytest.skip("the playwright Node driver is missing, so nothing was measured")
    if not (CLIENT_ROOT / "dist" / "style-guide.js").exists():
        pytest.skip("client/dist/style-guide.js is not built, so nothing was measured")
    run = subprocess.run(
        [node, str(PROBE), str(package), str(CLIENT_ROOT), theme, ",".join(map(str, WIDTHS)), "-"],
        capture_output=True, text=True, timeout=240, check=False,
    )
    if run.returncode != 0 and "Executable doesn't exist" in run.stderr:
        pytest.skip("playwright's Chromium is not installed, so nothing was measured")
    assert run.returncode == 0, f"the layout probe failed:\n{run.stderr[-2000:]}"
    return json.loads(run.stdout.strip().splitlines()[-1])["results"]


def test_pane_and_list_share_a_narrow_main_area_with_no_gap() -> None:
    for r in _probe("carnivore"):
        page, lst, pane, never, title = r["page"], r["list"], r["pane"], r["never"], r["title"]
        at = f"at {r['width']} px of page"
        assert pane["left"] >= page["left"] - SLACK and pane["right"] <= page["right"] + SLACK, (
            f"{at} the pane spans {pane['left']:.0f}..{pane['right']:.0f}, outside the page {page['left']:.0f}..{page['right']:.0f}"
        )
        assert never is not None, f"{at} the never-ran state is not drawn"
        assert never["left"] >= pane["left"] - SLACK and never["right"] <= pane["right"] + SLACK, f"{at} the never-ran state leaves the pane"
        if r["width"] - 2 >= DOCK_FROM:
            assert abs(lst["right"] - pane["left"]) <= SLACK, (
                f"{at} the list ends at {lst['right']:.0f} but the pane starts at {pane['left']:.0f}: a gap or an overlap"
            )
            assert pane["width"] <= PANE_MAX + SLACK, f"{at} the docked pane is {pane['width']:.0f} px, wider than {PANE_MAX}"
            assert title["height"] <= TITLE_ONE_ROW_MAX, f"{at} the title strip wraps to {title['height']:.0f} px"
        else:
            assert pane["width"] >= page["width"] - 2 - SLACK, f"{at} the pane is {pane['width']:.0f} px instead of covering the page"
        assert r["tree"] is not None, f"{at} the scheduled table is not drawn"
        assert r["treeName"] is not None and r["treeName"]["width"] >= TREE_NAME_MIN, (
            f"{at} the scheduled table's item column is squeezed to {r['treeName'] and round(r['treeName']['width'])} px"
        )

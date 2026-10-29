
from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.widgets import harness


def test_the_fit_check_goes_red_on_every_rule(page_and_base) -> None:
    page, base = page_and_base
    page.set_viewport_size({"width": 1600, "height": 900})
    render = harness.open_widget(page, base, "harness.fit-probe", "data", {"zone": "home", "size": "m", "theme": "carnivore"})
    assert render.error == ""
    findings = harness.show(page, "harness.fit-probe", "data", "home", "m", "carnivore").findings
    rules = {f["rule"] for f in findings}
    assert {"overflow-x", "overflow-y", "scrollbar-x", "clipped-text", "overlap", "bad-text"} <= rules, findings
    cuts = " ".join(f["detail"] for f in findings if f["rule"] == "clipped-text")
    assert "vertically" in cuts and "no ellipsis" in cuts, cuts
    wide = next(f for f in findings if f["rule"] == "overflow-x")
    assert wide["px"] >= 390, wide
    bad = " ".join(f["detail"] for f in findings if f["rule"] == "bad-text")
    assert "unknown" in bad or "session_row_id" in bad


def test_the_files_header_chip_fits_the_header_in_a_lab_sized_window(page_and_base) -> None:
    page, base = page_and_base
    page.set_viewport_size({"width": 416, "height": 440})
    first = {"zone": "terminal", "size": "m", "theme": "claude"}
    harness.open_widget(page, base, "core.files", "data", first, extra={"lab": "1"})
    findings = harness.show(page, "core.files", "data", "terminal", "m", "claude").findings
    assert [f for f in findings if f["rule"] == "overflow-y"] == [], findings


@pytest.mark.skipif(os.environ.get("CARNIVORE_WIDGET_FIT") != "1",
                    reason="the full widget capture takes minutes: set CARNIVORE_WIDGET_FIT=1 to run it")
def test_every_widget_passes_the_fit_check(tmp_path: Path) -> None:
    """Every widget, zone, standard size, theme and fixture draws with no fit finding."""
    from scripts.widgets.capture import main

    code = main(["--no-build", "--no-shots", "--out", str(tmp_path)])
    assert code != 2, "the capture could not determine (see its stderr)"
    assert code == 0, (tmp_path / "report.md").read_text(encoding="utf-8")[:6000]

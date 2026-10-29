
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.widgets import defect_allow, harness

PROBE = "harness.defect-probe"


def _probe(page, base: str, key: str, theme: str = "carnivore") -> dict:
    page.set_viewport_size({"width": 1600, "height": 900})
    render = harness.open_widget(page, base, key, "data", {"zone": "home", "size": "m", "theme": theme})
    assert render.error == ""
    harness.show(page, key, "data", "home", "m", theme)
    return harness.defects(page)


@pytest.mark.parametrize("theme", ["carnivore", "acid_trip"])
def test_every_detector_goes_red_on_its_region(page_and_base, theme: str) -> None:
    page, base = page_and_base
    report = _probe(page, base, PROBE, theme)
    found = report["findings"]

    def hits(region: str, rule: str, severity: str = "fail") -> list[dict]:
        return [f for f in found if region in f["selector"] and f["rule"] == rule and f["severity"] == severity]

    assert hits("wh-defect-overlap", "overlap"), found
    graphic = hits("wh-defect-graphic", "overlap")
    assert graphic and "graphic" in graphic[0]["detail"], found
    assert hits("wh-defect-clipped", "clipped"), found
    assert hits("wh-defect-ellipsis", "ellipsis", "warn"), found
    assert hits("wh-defect-tiny", "tiny-text") and hits("wh-defect-tiny", "tiny-text")[0]["px"] == 7, found
    assert hits("wh-defect-contrast", "low-contrast"), found
    assert hits("wh-defect-decor", "low-contrast", "warn"), found
    assert not hits("wh-defect-decor", "low-contrast"), "an aria-hidden element is reported, never failed"
    assert hits("wh-defect-wrap", "wrap"), found
    assert hits("wh-defect-escape", "escape"), found
    assert not [f for f in found if "wh-defect-clean" in f["selector"] or "wh-defect-truncatable" in f["selector"]], found
    assert report["checked"]["texts"] >= 10 and report["checked"]["graphics"] >= 1, report["checked"]


def test_a_cell_with_no_text_is_a_failure(page_and_base) -> None:
    page, base = page_and_base
    report = _probe(page, base, "harness.defect-probe-blank")
    assert report["checked"]["texts"] == 0
    assert [f["rule"] for f in report["findings"] if f["severity"] == "fail"] == ["no-text"], report


def _draw(key: str, rule: str = "overlap", **over) -> dict:
    finding = {"rule": rule, "severity": "fail", "selector": "span.oc-tile-figure:nth-child(1)", "px": 4, "detail": "x"}
    return {"key": key, "size": "small", "theme": "carnivore", "shape": "data", "findings": [finding], **over}


def test_the_allow_list_allows_matches_and_fails_stale_entries(tmp_path: Path) -> None:
    entries = [defect_allow.Allowance(widget="core.a", size="small", rule="overlap", reason="intended"),
               defect_allow.Allowance(widget="core.b", size="small", rule="clipped", reason="fixed since", todo=True)]
    verdict = defect_allow.apply([_draw("core.a"), _draw("core.b"), _draw("core.c")], entries)
    assert [d["key"] for d, _ in verdict.failing] == ["core.b", "core.c"]
    assert [e.widget for _, _, e in verdict.allowed] == ["core.a"]
    assert [e.widget for e in verdict.stale] == ["core.b"]
    assert defect_allow.apply([_draw("core.c")], entries).stale == [], "an entry for a widget not drawn is not judged"
    assert defect_allow.apply([_draw("core.b")], entries, judge_stale=False).stale == []
    bad = tmp_path / "allow.json"
    bad.write_text(json.dumps({"entries": [{"widget": "core.a", "size": "small", "rule": "overlap"}]}))
    with pytest.raises(defect_allow.AllowListError, match="reason"):
        defect_allow.load(bad)


def test_the_allow_list_file_is_valid() -> None:
    rules = {"overlap", "clipped", "escape", "tiny-text", "low-contrast", "wrap", "no-text"}
    for entry in defect_allow.load():
        assert entry.rule in rules, entry


STAT_TILES = ("core.stat-running", "core.stat-sessions", "core.stat-projects", "core.stat-ledger", "core.stat-alive",
              "core.stat-subagents")


@pytest.mark.parametrize("viewport", ["page", "box"])
def test_the_stat_tiles_read_cleanly(page_and_base, tmp_path: Path, viewport: str) -> None:
    from scripts.widgets.defects import SHAPES, sweep_widget  # noqa: PLC0415

    page, base = page_and_base
    widgets, themes = harness.catalog(page, base)
    draws = [draw for widget in widgets if widget["key"] in STAT_TILES
             for draw in sweep_widget(page, base, widget, list(themes), list(SHAPES), tmp_path, viewport)]
    assert {d["key"] for d in draws} == set(STAT_TILES) and len(draws) == 6 * 2 * len(themes) * len(SHAPES)
    assert not [d for d in draws if d["error"]], [d["error"] for d in draws if d["error"]]
    assert all(d["checked"]["texts"] > 0 for d in draws)
    verdict = defect_allow.apply(draws, defect_allow.load())
    assert not verdict.failing, [(d["key"], d["size"], d["theme"], d["shape"], f["detail"]) for d, f in verdict.failing]
    assert not verdict.stale, verdict.stale


@pytest.mark.skipif(os.environ.get("CARNIVORE_WIDGET_DEFECTS") != "1",
                    reason="the whole sweep takes about half an hour: set CARNIVORE_WIDGET_DEFECTS=1 to run it")
def test_every_widget_reads_cleanly(tmp_path: Path) -> None:
    """Every widget, named size, theme and data shape: no unallowed defect, no stale allowance."""
    from scripts.widgets.defects import main as sweep  # noqa: PLC0415

    code = sweep(["--no-build", "--out", str(tmp_path)])
    assert code != 2, "the sweep could not determine (see its stderr)"
    assert code == 0, (tmp_path / "report.md").read_text(encoding="utf-8")[:6000]

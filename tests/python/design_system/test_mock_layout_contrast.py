from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.contrast.catalog_themes import CATALOG_THEMES
from scripts.contrast.color_utils import ColorResolutionError, list_theme_ids, load_theme_vars
from scripts.contrast.mock_layout import MockCssError, MockStyle, failing, measure, measure_bundled, read_style

STYLE = read_style()
BUNDLED = list_theme_ids()


def _rgb(hexcode: str) -> tuple[int, int, int]:
    return (int(hexcode[1:3], 16), int(hexcode[3:5], 16), int(hexcode[5:7], 16))


def _all_rows(style: MockStyle) -> dict[str, dict[str, tuple[float, float]]]:
    rows: dict[str, dict[str, tuple[float, float]]] = {}
    for tid in BUNDLED:
        try:
            rows[tid] = measure_bundled(load_theme_vars(tid), style)
        except ColorResolutionError as err:
            pytest.fail(f"{tid}: could not resolve a color: {err}")
    for tid, (ground, text) in CATALOG_THEMES.items():
        rows[f"catalog:{tid}"] = measure(_rgb(ground), _rgb(text), style)
    return rows


def test_every_shipped_theme_is_measured_and_counted() -> None:
    rows = _all_rows(STYLE)
    assert len(BUNDLED) >= 12 and len(CATALOG_THEMES) >= 16
    assert len(rows) == len(BUNDLED) + len(CATALOG_THEMES)
    assert all(len(r) >= 6 for r in rows.values())


def test_the_frame_and_the_edged_cell_body_read_under_every_theme(capsys: pytest.CaptureFixture[str]) -> None:
    rows = _all_rows(STYLE)
    bad = {tid: failing(r) for tid, r in rows.items() if failing(r)}
    with capsys.disabled():
        print(f"\nmock layout contrast, {len(rows)} themes ({len(BUNDLED)} bundled, {len(CATALOG_THEMES)} catalog):")
        for name in rows[BUNDLED[0]]:
            lowest = min(rows.items(), key=lambda item: item[1].get(name, (99.0, 0.0))[0] if name in item[1] else 99.0)
            print(f"  {name:34} lowest {lowest[1][name][0]:5.2f} (floor {lowest[1][name][1]}) on {lowest[0]}")
    assert not bad, "pairs under their floor: " + "; ".join(f"{tid}: {pairs}" for tid, pairs in bad.items())


def test_the_stylesheet_is_read_not_assumed() -> None:
    assert 0.5 < STYLE.line_share <= 1.0 and 0.0 < STYLE.head_share < STYLE.line_share
    assert STYLE.lines_text in ("primary", "secondary", "muted") and STYLE.head_text in ("primary", "secondary", "muted")


def test_negative_control_weaker_lines_go_red() -> None:
    weaker = replace(STYLE, line_share=0.20)
    bad = {tid: failing(r) for tid, r in _all_rows(weaker).items() if failing(r)}
    assert bad, "a 20 percent line passed every theme: the check measures nothing"
    assert any("frame line on card body" in pairs for pairs in bad.values())


def test_negative_control_a_padding_fill_as_quiet_as_its_neighbours_goes_red() -> None:
    flat = replace(STYLE, head_share=0.06)
    assert any("padding fill on card body" in failing(r) for r in _all_rows(flat).values())


def test_negative_control_a_dim_ink_goes_red() -> None:
    rows = measure((30, 31, 41), (248, 248, 242), STYLE, lines_ink=(70, 72, 90))
    assert "sample text on stage" in failing(rows)


def test_negative_control_a_missing_declaration_is_its_own_failure(tmp_path) -> None:
    css = tmp_path / "mock.css"
    css.write_text(".wp-mock { padding: 8px; }\n", encoding="utf-8")
    with pytest.raises(MockCssError):
        read_style(css)

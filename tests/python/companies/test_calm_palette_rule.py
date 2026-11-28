
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.project_colors.calm_remap import assign_calm_colors, nearest_calm_color, sibling_key
from src.core.project_colors.color_math import contrast_ratio, delta_e_hex, oklch
from src.core.project_colors.palette import SOFT_PALETTE

ROOT = Path(__file__).resolve().parents[3]
THEMES = sorted((ROOT / "client/css/themes").glob("*/theme.json"))

MIN_DE_PAIR = 9.5
MIN_CHROMA = 0.11
MIN_CONTRAST = 2.0


def _grounds():
    grounds = []
    for path in THEMES:
        vars_ = json.loads(path.read_text())["cssVars"]
        grounds += [vars_["--color-bg"].lower(), vars_["--color-bg-card"].lower()]
    return grounds


GROUNDS = _grounds()


def _violations(hex_: str):
    out = []
    chroma = round(oklch(hex_)[1], 3)
    if chroma < MIN_CHROMA:
        out.append(f"chroma {chroma:.3f} < {MIN_CHROMA}")
    worst = min(contrast_ratio(hex_, g) for g in GROUNDS)
    if worst < MIN_CONTRAST:
        out.append(f"contrast {worst:.2f} < {MIN_CONTRAST} on a theme ground")
    return out


def test_every_shipped_theme_was_read():
    assert len(THEMES) >= 12 and len(GROUNDS) >= 24


@pytest.mark.parametrize("hex_", SOFT_PALETTE)
def test_palette_entry_is_vibrant_and_readable_on_every_theme(hex_):
    assert _violations(hex_) == []


def test_palette_spans_full_wheel_and_entries_are_distinguishable():
    assert len(SOFT_PALETTE) == len(set(SOFT_PALETTE)) == 12
    quadrants = {int(oklch(h)[2] // 90) % 4 for h in SOFT_PALETTE}
    assert quadrants == {0, 1, 2, 3}
    for i, a in enumerate(SOFT_PALETTE):
        for b in SOFT_PALETTE[i + 1:]:
            assert delta_e_hex(a, b) >= MIN_DE_PAIR, (a, b)


def test_the_rule_rejects_dull_grays_and_unreadable_light_pastels():
    assert any("chroma" in v for v in _violations("#8a8a8a"))
    assert any("chroma" in v for v in _violations("#966356"))
    assert any("contrast" in v for v in _violations("#e8e48a"))


def test_remap_lands_on_the_palette_and_keeps_siblings_apart():
    live = [("Fleet", "#7bbbc1"), ("Fleet Docker", "#7bc1aa"), ("Fleet Monitoring", "#7bc187"),
            ("Shelving", "#7b89c1"), ("Shelving Catalog", "#c1897b"), ("Shelving catalog site", "#c1a57b"),
            ("Media", "#c1897b"), ("Media Pipeline", "#7ba4c1"), ("N8N", "cyan"), ("Trader", None)]
    mapping = assign_calm_colors(live)
    assert set(mapping) == {n for n, _ in live} and set(mapping.values()) <= set(SOFT_PALETTE)
    for prefix in ("fleet", "shelving", "media"):
        colors = [c for n, c in mapping.items() if sibling_key(n) == prefix]
        assert len(colors) == len(set(colors)) > 1
    assert assign_calm_colors(live) == mapping
    assert nearest_calm_color("#c17b87") in SOFT_PALETTE

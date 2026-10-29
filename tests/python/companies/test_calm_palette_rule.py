
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.project_colors.calm_remap import assign_calm_colors, nearest_calm_color, sibling_key
from src.core.project_colors.color_math import contrast_ratio, delta_e_hex, oklch
from src.core.project_colors.palette import SOFT_PALETTE

ROOT = Path(__file__).resolve().parents[3]
THEMES = sorted((ROOT / "client/css/themes").glob("*/theme.json"))

MIN_DE_SEMANTIC = 10.0
MIN_DE_PAIR = 7.4
MIN_CHROMA = 0.07
MAX_CHROMA = 0.16
MIN_CONTRAST = 2.0

SEMANTIC_KEYS = (
    "--color-accent", "--color-accent-strong", "--color-success", "--color-warning", "--color-danger",
    "--color-info", "--color-status-connected", "--color-status-error", "--color-status-pending", "--color-fg-muted",
)
LED_DEAD = "#494c4f"
OC_VIOLET = "#a98fe0"
OLD_WHEEL = (
    "#c17b87", "#c1897b", "#c1a57b", "#c1b87b", "#aac17b", "#7bc187",
    "#7bc1aa", "#7bbbc1", "#7ba4c1", "#7b89c1", "#987bc1", "#c17bb3",
)

WHEEL_STILL_ALLOWED = ("#7b89c1", "#c17bb3")


def _semantic_and_grounds():
    semantic = [("led dead", LED_DEAD), ("oc violet", OC_VIOLET)]
    grounds = []
    for path in THEMES:
        vars_ = json.loads(path.read_text())["cssVars"]
        for key in SEMANTIC_KEYS:
            value = vars_.get(key, "")
            if value.startswith("#") and len(value) == 7:
                semantic.append((f"{path.parent.name} {key}", value.lower()))
        grounds += [vars_["--color-bg"].lower(), vars_["--color-bg-card"].lower()]
    return semantic, grounds


SEMANTIC, GROUNDS = _semantic_and_grounds()


def _violations(hex_: str):
    out = []
    nearest = min(SEMANTIC, key=lambda s: delta_e_hex(hex_, s[1]))
    de = delta_e_hex(hex_, nearest[1])
    if de < MIN_DE_SEMANTIC:
        out.append(f"deltaE {de:.1f} < {MIN_DE_SEMANTIC} from {nearest[0]} {nearest[1]}")
    chroma = round(oklch(hex_)[1], 2)
    if not MIN_CHROMA <= chroma <= MAX_CHROMA:
        out.append(f"chroma {chroma:.3f} outside {MIN_CHROMA}..{MAX_CHROMA}")
    worst = min(contrast_ratio(hex_, g) for g in GROUNDS)
    if worst < MIN_CONTRAST:
        out.append(f"contrast {worst:.2f} < {MIN_CONTRAST} on a theme ground")
    return out


def test_every_shipped_theme_was_read():
    assert len(THEMES) >= 12 and len(SEMANTIC) >= 100 and len(GROUNDS) >= 24


@pytest.mark.parametrize("hex_", SOFT_PALETTE)
def test_palette_entry_stays_clear_of_every_semantic_color(hex_):
    assert _violations(hex_) == []


def test_palette_entries_are_distinguishable_from_each_other():
    assert len(SOFT_PALETTE) == len(set(SOFT_PALETTE)) >= 10
    for i, a in enumerate(SOFT_PALETTE):
        for b in SOFT_PALETTE[i + 1:]:
            assert delta_e_hex(a, b) >= MIN_DE_PAIR, (a, b)


def test_the_rule_can_fail_the_old_status_like_colors_are_refused():
    failing = [h for h in OLD_WHEEL if _violations(h)]
    assert set(failing) == set(OLD_WHEEL) - set(WHEEL_STILL_ALLOWED)
    assert any("deltaE" in v for v in _violations("#7bc187"))
    assert any("contrast" in v for v in _violations("#c1b87b"))
    assert any("chroma" in v for v in _violations("#ff4652"))
    assert any("chroma" in v for v in _violations("#8a8a8a"))


def test_remap_lands_on_the_palette_and_keeps_siblings_apart():
    live = [("Harbor", "#7bbbc1"), ("Harbor Docker", "#7bc1aa"), ("Harbor Monitoring", "#7bc187"),
            ("Storefront", "#7b89c1"), ("Storefront Catalog", "#c1897b"), ("Storefront catalog site", "#c1a57b"),
            ("Media", "#c1897b"), ("Media Studio", "#7ba4c1"), ("NFLOW", "cyan"), ("Ledgerbot", None)]
    mapping = assign_calm_colors(live)
    assert set(mapping) == {n for n, _ in live} and set(mapping.values()) <= set(SOFT_PALETTE)
    for prefix in ("harbor", "storefront", "media"):
        colors = [c for n, c in mapping.items() if sibling_key(n) == prefix]
        assert len(colors) == len(set(colors)) > 1
    assert assign_calm_colors(live) == mapping
    assert nearest_calm_color("#c17b87") in SOFT_PALETTE

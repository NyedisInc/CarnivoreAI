
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BAND_THEMES = ("dracula", "carnivore-light")


def theme_vars(theme: str) -> dict[str, str]:
    data = json.loads((REPO / "client" / "css" / "themes" / theme / "theme.json").read_text())
    return {k: v for k, v in data["cssVars"].items() if k.startswith("--")}


def luminance(color: str) -> float:
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


def test_luminance_reads_both_serializations() -> None:
    assert luminance("rgb(0, 0, 0)") < luminance("color(srgb 0.5 0.5 0.5)") < luminance("rgb(255, 255, 255)")
    with pytest.raises(ValueError):
        luminance("transparent")


def luma(rgb: list[int]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def test_luma_orders_black_gray_white() -> None:
    assert luma([0, 0, 0]) == 0.0 < luma([128, 128, 128]) < luma([255, 255, 255])


@pytest.mark.parametrize("theme", BAND_THEMES)
def test_the_measured_themes_carry_two_different_grounds(theme: str) -> None:
    found = theme_vars(theme)
    assert {"--color-header-bg", "--color-bg-page"} <= found.keys(), f"{theme} lost a ground: {sorted(found)[:8]}"
    assert found["--color-header-bg"] != found["--color-bg-page"], f"{theme}: band equals page, the browser half proves nothing"

from __future__ import annotations

import itertools
import json
import math
import re

import pytest

from tests.python.design_system._sources import REPO

THEMES = sorted((REPO / "client" / "css" / "themes").glob("*/theme.json"))
TOKENS = (REPO / "web" / "src" / "opscenter" / "tokens.css").read_text()
MIN_DELTA_E = 6.0
MIN_CONTRAST = 3.0
_SERIES = re.compile(
    r"--oc-series-(\d): oklch\(from var\(--color-bg, #[0-9a-fA-F]{6}\) calc\((.*)\) ([\d.]+) (\d+)\);"
)


def _hex(value: str) -> tuple[float, float, float]:
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _oklab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = (_lin(c) for c in rgb)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def _oklch_to_rgb(lightness: float, chroma: float, hue: float) -> tuple[float, float, float]:
    def convert(c: float) -> tuple[float, float, float]:
        a, b = c * math.cos(math.radians(hue)), c * math.sin(math.radians(hue))
        l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
        m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
        s = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
        lin = (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
               -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
               -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)
        return lin  # type: ignore[return-value]

    lo, hi = 0.0, chroma
    if all(-1e-4 <= v <= 1 + 1e-4 for v in convert(chroma)):
        lo = chroma
    else:
        for _ in range(30):
            mid = (lo + hi) / 2
            if all(-1e-4 <= v <= 1 + 1e-4 for v in convert(mid)):
                lo = mid
            else:
                hi = mid
    enc = lambda v: 12.92 * v if v <= 0.0031308 else 1.055 * max(v, 0) ** (1 / 2.4) - 0.055
    return tuple(min(1.0, max(0.0, enc(v))) for v in convert(lo))  # type: ignore[return-value]


def _luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _series(ground: tuple[float, float, float]) -> list[tuple[float, float, float]]:
    ground_l = _oklab(ground)[0]
    out = []
    for n, expr, chroma, hue in _SERIES.findall(TOKENS):
        lightness = eval_l(expr, ground_l)
        out.append(_oklch_to_rgb(lightness, float(chroma), float(hue)))
    return out


def eval_l(expr: str, l: float) -> float:
    py = expr.replace("clamp(", "_clamp(")
    if re.search(r"[^\d\s.+\-*/(),l_clamp]", py):
        raise ValueError(f"unexpected calc body: {expr}")
    return float(eval(py, {"__builtins__": {}}, {"l": l, "_clamp": lambda a, b, c: min(max(b, a), c)}))  # noqa: S307


def test_tokens_declare_eight_series_and_a_display_size() -> None:
    assert len(_SERIES.findall(TOKENS)) == 8
    for n in range(1, 9):
        assert TOKENS.count(f"--oc-series-{n}:") == 2, f"series {n} lacks a fallback"
    assert "--oc-fs-display:" in TOKENS


@pytest.mark.parametrize("path", THEMES, ids=lambda p: p.parent.name)
def test_series_palette_readable_and_distinct(path) -> None:
    ground = _hex(json.loads(path.read_text())["cssVars"]["--color-bg"])
    colours = _series(ground)
    assert len(colours) == 8
    lab = [_oklab(c) for c in colours]
    for i, j in itertools.combinations(range(8), 2):
        de = 100 * math.dist(lab[i], lab[j])
        assert de >= MIN_DELTA_E, f"{path.parent.name}: series {i + 1} vs {j + 1} delta {de:.1f}"
    gl = _luminance(ground)
    for i, c in enumerate(colours):
        y = _luminance(c)
        ratio = (max(y, gl) + 0.05) / (min(y, gl) + 0.05)
        assert ratio >= MIN_CONTRAST, f"{path.parent.name}: series {i + 1} contrast {ratio:.2f}"


def test_the_palette_check_can_fail() -> None:
    same = _oklab((0.5, 0.5, 0.5))
    assert 100 * math.dist(same, same) < MIN_DELTA_E
    assert (_luminance((0.5, 0.5, 0.5)) + 0.05) / (_luminance((0.5, 0.5, 0.5)) + 0.05) < MIN_CONTRAST

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STYLES_CSS = REPO_ROOT / "client" / "css" / "styles.css"
THEMES_DIR = REPO_ROOT / "client" / "css" / "themes"

_ROOT_BLOCK_RE = re.compile(r":root\s*\{(.*?)\n\}", re.DOTALL)
_VAR_DECL_RE = re.compile(r"--([a-zA-Z0-9_-]+)\s*:\s*([^;]+);")
_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB_RE = re.compile(
    r"^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$"
)
_VAR_REF_RE = re.compile(r"var\(\s*--([a-zA-Z0-9_-]+)\s*(?:,\s*(.+))?\)$")


class ColorResolutionError(Exception):

    def __init__(self, token: str, raw_value: str, reason: str):
        self.token = token
        self.raw_value = raw_value
        self.reason = reason
        super().__init__(f"{token}: cannot resolve {raw_value!r} ({reason})")


def parse_base_root_vars() -> dict[str, str]:
    css = STYLES_CSS.read_text(encoding="utf-8")
    match = _ROOT_BLOCK_RE.search(css)
    if not match:
        raise ColorResolutionError("(root block)", "", "no :root {} block found in styles.css")
    body = match.group(1)
    out: dict[str, str] = {}
    for m in _VAR_DECL_RE.finditer(body):
        out[m.group(1)] = m.group(2).strip()
    return out


def list_theme_ids() -> list[str]:
    return sorted(
        p.parent.name for p in THEMES_DIR.glob("*/theme.json")
    )


def load_theme_vars(theme_id: str) -> dict[str, str]:
    base = parse_base_root_vars()
    manifest_path = THEMES_DIR / theme_id / "theme.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    overrides = manifest.get("cssVars", {})
    for k, v in overrides.items():
        assert k.startswith("--"), f"{theme_id}: cssVars key {k!r} missing leading --"
        base[k[2:]] = v.strip()
    return base


def _clamp(v: float) -> int:
    return max(0, min(255, round(v)))


def _parse_hex(value: str) -> tuple[int, int, int]:
    h = value.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def resolve_color(
    token: str,
    vars_table: dict[str, str],
    _seen: frozenset[str] | None = None,
) -> tuple[int, int, int]:
    seen = _seen or frozenset()
    if token in seen:
        raise ColorResolutionError(token, vars_table.get(token, ""), "circular var() reference")
    if token not in vars_table:
        raise ColorResolutionError(token, "", "token not defined in base or theme")
    raw = vars_table[token].strip()
    return _resolve_value(token, raw, vars_table, seen | {token})


def _resolve_value(
    token: str, raw: str, vars_table: dict[str, str], seen: frozenset[str]
) -> tuple[int, int, int]:
    var_match = _VAR_REF_RE.match(raw)
    if var_match:
        ref_name, fallback = var_match.group(1), var_match.group(2)
        if ref_name in vars_table:
            return resolve_color(ref_name, vars_table, seen)
        if fallback is not None:
            return _resolve_value(token, fallback.strip(), vars_table, seen)
        raise ColorResolutionError(token, raw, f"var(--{ref_name}) has no fallback and is undefined")

    if _HEX_RE.match(raw):
        return _parse_hex(raw)

    rgb_match = _RGB_RE.match(raw)
    if rgb_match:
        r, g, b = (float(rgb_match.group(i)) for i in (1, 2, 3))
        return (_clamp(r), _clamp(g), _clamp(b))

    raise ColorResolutionError(token, raw, "unparseable color value (gradient, hsl/oklch, image, or literal keyword)")


def resolve_alpha(token: str, vars_table: dict[str, str]) -> float:
    raw = vars_table.get(token, "")
    m = _RGB_RE.match(raw.strip())
    if m and m.group(4) is not None:
        return float(m.group(4))
    return 1.0


def composite_over(fg_token: str, under_token: str, vars_table: dict[str, str]) -> tuple[int, int, int]:
    fg_rgb = resolve_color(fg_token, vars_table)
    alpha = resolve_alpha(fg_token, vars_table)
    under_rgb = resolve_color(under_token, vars_table)
    return tuple(
        _clamp(fg_rgb[i] * alpha + under_rgb[i] * (1 - alpha)) for i in range(3)
    )


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def chan(c: int) -> float:
        c_norm = c / 255.0
        return c_norm / 12.92 if c_norm <= 0.03928 else ((c_norm + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    l1 = relative_luminance(fg) + 0.05
    l2 = relative_luminance(bg) + 0.05
    return max(l1, l2) / min(l1, l2)


def _srgb_to_linear(c: int) -> float:
    c_norm = c / 255.0
    return c_norm / 12.92 if c_norm <= 0.04045 else ((c_norm + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> int:
    c = max(0.0, min(1.0, c))
    s = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return _clamp(s * 255)


def _rgb_to_oklab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (v ** (1 / 3) if v >= 0 else -((-v) ** (1 / 3)) for v in (l, m, s))
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def _oklab_to_rgb(lab: tuple[float, float, float]) -> tuple[int, int, int]:
    lightness, a, b = lab
    l_ = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bb = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    return tuple(_linear_to_srgb(c) for c in (r, g, bb))


def mix_oklab(
    top: tuple[int, int, int], bottom: tuple[int, int, int], top_percent: float
) -> tuple[int, int, int]:
    frac = top_percent / 100.0
    lab_top, lab_bottom = _rgb_to_oklab(top), _rgb_to_oklab(bottom)
    mixed = tuple(lab_top[i] * frac + lab_bottom[i] * (1 - frac) for i in range(3))
    return _oklab_to_rgb(mixed)


@dataclass(frozen=True)
class Pairing:

    name: str
    fg_token: str
    bg_token: str
    threshold: float
    source: str
    bg_under_token: str | None = None

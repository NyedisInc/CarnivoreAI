from __future__ import annotations

import json
import sys
from pathlib import Path

from .color_utils import (
    REPO_ROOT,
    THEMES_DIR,
    _oklab_to_rgb,
    _rgb_to_oklab,
    contrast_ratio,
    list_theme_ids,
    parse_base_root_vars,
    resolve_alpha,
    resolve_color,
)

AA_TEXT = 4.5
AA_BOUNDARY = 3.0
TEXT_ROLES: dict[str, str] = {
    "primary": "color-fg", "secondary": "color-fg-muted", "muted": "color-fg-subtle", "faint": "color-fg-faint",
    "accent": "color-accent", "success": "color-success", "warning": "color-warning", "danger": "color-danger",
    "info": "color-info",
}
BASELINE = REPO_ROOT / "tests" / "fixtures" / "design_contrast_roles_baseline.json"
GROUNDS = ("sunken", "base", "band", "raised", "overlay")
Rgb = tuple[int, int, int]


def _mix(a: Rgb, b: Rgb, share_b: float) -> Rgb:
    return tuple(round(a[i] * (1 - share_b) + b[i] * share_b) for i in range(3))  # type: ignore[return-value]


def _sunken(base: Rgb) -> Rgb:
    lightness, a, b = _rgb_to_oklab(base)
    return _oklab_to_rgb((max(0.0, lightness - 0.03), a, b))


def _ink(token: str, ground: Rgb, table: dict[str, str]) -> Rgb:
    rgb = resolve_color(token, table)
    alpha = resolve_alpha(token, table)
    return tuple(round(rgb[i] * alpha + ground[i] * (1 - alpha)) for i in range(3))  # type: ignore[return-value]


def grounds_of(table: dict[str, str]) -> dict[str, Rgb]:
    base = resolve_color("color-bg-page", table)
    fg = resolve_color("color-fg", table)
    return {
        "sunken": _sunken(base),
        "base": base,
        "band": resolve_color("color-header-bg", table),
        "raised": _mix(base, fg, 0.06),
        "overlay": _mix(base, fg, 0.12),
    }


def matrix(table: dict[str, str]) -> dict[str, tuple[float, float]]:
    grounds = grounds_of(table)
    out: dict[str, tuple[float, float]] = {}
    for role, token in TEXT_ROLES.items():
        for name in GROUNDS:
            ground = grounds[name]
            out[f"{role} on {name}"] = (round(contrast_ratio(_ink(token, ground, table), ground), 2), AA_TEXT)
    fg = resolve_color("color-fg", table)
    for name in ("sunken", "base", "raised"):
        line = _mix(grounds["base"], fg, 0.55)
        out[f"control line on {name}"] = (round(contrast_ratio(line, grounds[name]), 2), AA_BOUNDARY)
    accent = resolve_color("color-accent", table)
    out["on-accent on accent"] = (round(contrast_ratio(_ink("color-on-accent", accent, table), accent), 2), AA_TEXT)
    return out


def failing(table: dict[str, str]) -> dict[str, float]:
    return {pair: ratio for pair, (ratio, minimum) in matrix(table).items() if ratio < minimum}


def load_manifest_vars(path: Path) -> dict[str, str]:
    table = parse_base_root_vars()
    for key, value in json.loads(path.read_text(encoding="utf-8")).get("cssVars", {}).items():
        table[key[2:]] = str(value).strip()
    return table


def bundled() -> dict[str, dict[str, str]]:
    return {tid: load_manifest_vars(THEMES_DIR / tid / "theme.json") for tid in list_theme_ids()}


def write_baseline() -> None:
    doc = {
        "about": "bundled themes' role pairs below their minimum (scripts/contrast/roles.py, issue #2033 guard G2); "
                 "a theme may not add a pair or lower a ratio",
        "themes": {tid: failing(table) for tid, table in bundled().items()},
    }
    BASELINE.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def compare(found: dict[str, dict[str, float]], baseline: dict[str, dict[str, float]],
            slack: float = 0.01) -> tuple[list[str], list[str]]:
    worse: list[str] = []
    stale: list[str] = []
    for tid in sorted(set(found) | set(baseline)):
        have, known = found.get(tid, {}), baseline.get(tid, {})
        for pair, ratio in sorted(have.items()):
            if pair not in known:
                worse.append(f"{tid}: {pair} {ratio:.2f} newly below its minimum")
            elif ratio < known[pair] - slack:
                worse.append(f"{tid}: {pair} fell from {known[pair]:.2f} to {ratio:.2f}")
            elif ratio > known[pair] + slack:
                stale.append(f"{tid}: {pair} rose from {known[pair]:.2f} to {ratio:.2f}")
        stale.extend(f"{tid}: {pair} now passes" for pair in sorted(set(known) - set(have)))
    return worse, stale


def main(argv: list[str]) -> int:
    if argv == ["--write-baseline"]:
        write_baseline()
        argv = []
    themes = {Path(p).parent.name: load_manifest_vars(Path(p)) for p in argv} if argv else bundled()
    total = 0
    for tid, table in themes.items():
        fails = failing(table)
        total += len(fails)
        worst = min(fails.items(), key=lambda kv: kv[1]) if fails else None
        print(f"{tid:18} {len(fails):3} below minimum" + (f"; worst {worst[0]} {worst[1]:.2f}" if worst else ""))
    print(f"total failing pairs: {total} across {len(themes)} themes, {len(matrix(next(iter(themes.values()))))} each")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

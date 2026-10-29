#!/usr/bin/env python3
from __future__ import annotations

import argparse
import colorsys
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.contrast.audit_themes import KNOWN_CSS_OVERRIDES  # noqa: E402
from scripts.contrast.color_utils import (  # noqa: E402
    THEMES_DIR,
    composite_over,
    contrast_ratio,
    list_theme_ids,
    load_theme_vars,
    relative_luminance,
    resolve_color,
)
from scripts.contrast.pairings import PAIRINGS  # noqa: E402

MARGIN = 0.05


def hex_of(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def relight(rgb: tuple[int, int, int], target_l: float) -> tuple[int, int, int]:
    r, g, b = (c / 255.0 for c in rgb)
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    r2, g2, b2 = colorsys.hls_to_rgb(h, max(0.0, min(1.0, target_l)), s)
    return (round(r2 * 255), round(g2 * 255), round(b2 * 255))


def solve_lightness(rgb: tuple[int, int, int], bg_rgb: tuple[int, int, int],
                     threshold: float, lighten: bool) -> tuple[int, int, int]:
    r, g, b = (c / 255.0 for c in rgb)
    _h, l0, _s = colorsys.rgb_to_hls(r, g, b)
    lo, hi = (l0, 1.0) if lighten else (0.0, l0)
    best = rgb
    for _ in range(40):
        mid = (lo + hi) / 2
        candidate = relight(rgb, mid)
        ratio = contrast_ratio(candidate, bg_rgb)
        if ratio >= threshold + MARGIN:
            best = candidate
            if lighten:
                hi = mid
            else:
                lo = mid
        else:
            if lighten:
                lo = mid
            else:
                hi = mid
    return best


def fix_theme(theme_id: str, dry_run: bool) -> list[dict]:
    manifest_path = THEMES_DIR / theme_id / "theme.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cssvars = manifest.setdefault("cssVars", {})
    vars_table = load_theme_vars(theme_id)

    changes: dict[str, dict] = {}
    for _pass in range(6):
        rows = _evaluate_against(vars_table)
        failing = [
            r for r in rows if r["status"] == "FAIL"
            and (theme_id, r["pairing"]) not in KNOWN_CSS_OVERRIDES
        ]
        if not failing:
            break
        for r in failing:
            pairing = next(p for p in PAIRINGS if p.name == r["pairing"] and True)
            fg_token = pairing.fg_token
            bg_rgb = (
                composite_over(pairing.bg_token, pairing.bg_under_token, vars_table)
                if pairing.bg_under_token
                else resolve_color(pairing.bg_token, vars_table)
            )
            fg_rgb = resolve_color(fg_token, vars_table)
            bg_lum = relative_luminance(bg_rgb)
            fg_lum = relative_luminance(fg_rgb)
            lighten = fg_lum >= bg_lum
            fixed_rgb = solve_lightness(fg_rgb, bg_rgb, pairing.threshold, lighten)
            achieved = contrast_ratio(fixed_rgb, bg_rgb)

            if achieved < pairing.threshold:
                opposite = solve_lightness(fg_rgb, bg_rgb, pairing.threshold, not lighten)
                if contrast_ratio(opposite, bg_rgb) > achieved:
                    fixed_rgb = opposite
                    achieved = contrast_ratio(fixed_rgb, bg_rgb)
                if achieved < pairing.threshold and not pairing.bg_under_token:
                    bg_lighten = bg_lum < 0.5
                    new_bg = solve_lightness(bg_rgb, fixed_rgb, pairing.threshold, bg_lighten)
                    bg_before = vars_table.get(pairing.bg_token, "")
                    bg_after = hex_of(new_bg)
                    vars_table[pairing.bg_token] = bg_after
                    bkey = f"--{pairing.bg_token}"
                    if bkey not in changes:
                        changes[bkey] = {"token": bkey, "before": bg_before, "after": bg_after}
                    else:
                        changes[bkey]["after"] = bg_after
                    fixed_rgb = solve_lightness(fg_rgb, new_bg, pairing.threshold, lighten)

            before_hex = vars_table.get(fg_token, "")
            after_hex = hex_of(fixed_rgb)
            vars_table[fg_token] = after_hex
            key = f"--{fg_token}"
            if key not in changes:
                changes[key] = {"token": key, "before": before_hex, "after": after_hex}
            else:
                changes[key]["after"] = after_hex

    if not dry_run and changes:
        for c in changes.values():
            cssvars[c["token"]] = c["after"]
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    return list(changes.values())


def _evaluate_against(vars_table: dict[str, str]) -> list[dict]:
    from scripts.contrast.color_utils import ColorResolutionError
    rows = []
    for p in PAIRINGS:
        try:
            fg_rgb = resolve_color(p.fg_token, vars_table)
            bg_rgb = (
                composite_over(p.bg_token, p.bg_under_token, vars_table)
                if p.bg_under_token
                else resolve_color(p.bg_token, vars_table)
            )
        except ColorResolutionError as exc:
            rows.append({"theme": "?", "pairing": p.name, "status": "COULD_NOT_EVALUATE", "detail": str(exc)})
            continue
        ratio = contrast_ratio(fg_rgb, bg_rgb)
        rows.append({"theme": "?", "pairing": p.name, "status": "PASS" if ratio >= p.threshold else "FAIL", "ratio": ratio})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--theme", default=None)
    args = ap.parse_args()

    themes = [args.theme] if args.theme else list_theme_ids()
    for t in themes:
        changes = fix_theme(t, args.dry_run)
        if changes:
            print(f"=== {t} ===")
            for c in changes:
                print(f"  {c['token']:28s} {c['before']:>9s} -> {c['after']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

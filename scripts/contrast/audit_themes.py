#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.contrast.color_utils import (  # noqa: E402
    ColorResolutionError,
    composite_over,
    contrast_ratio,
    list_theme_ids,
    load_theme_vars,
    resolve_color,
)
from scripts.contrast.pairings import PAIRINGS  # noqa: E402

KNOWN_CSS_OVERRIDES: dict = {}


def evaluate(theme_id: str):
    vars_table = load_theme_vars(theme_id)
    rows = []
    for p in PAIRINGS:
        override = KNOWN_CSS_OVERRIDES.get((theme_id, p.name))
        if override:
            ratio = contrast_ratio(override["fg"], override["bg"])
            status = "PASS" if ratio >= p.threshold else "FAIL"
            rows.append({
                "theme": theme_id, "pairing": p.name,
                "fg": p.fg_token, "bg": p.bg_token,
                "ratio": round(ratio, 2), "threshold": p.threshold,
                "status": status,
                "detail": f"CSS-OVERRIDE #{'%02x%02x%02x' % override['fg']} on "
                          f"#{'%02x%02x%02x' % override['bg']} ({override['note']})",
            })
            continue
        try:
            fg_rgb = resolve_color(p.fg_token, vars_table)
            if p.bg_under_token:
                bg_rgb = composite_over(p.bg_token, p.bg_under_token, vars_table)
            else:
                bg_rgb = resolve_color(p.bg_token, vars_table)
        except ColorResolutionError as exc:
            rows.append({
                "theme": theme_id, "pairing": p.name,
                "fg": p.fg_token, "bg": p.bg_token,
                "ratio": None, "threshold": p.threshold,
                "status": "COULD_NOT_EVALUATE",
                "detail": str(exc),
            })
            continue
        ratio = contrast_ratio(fg_rgb, bg_rgb)
        status = "PASS" if ratio >= p.threshold else "FAIL"
        rows.append({
            "theme": theme_id, "pairing": p.name,
            "fg": p.fg_token, "bg": p.bg_token,
            "ratio": round(ratio, 2), "threshold": p.threshold,
            "status": status,
            "detail": f"#{'%02x%02x%02x' % fg_rgb} on #{'%02x%02x%02x' % bg_rgb}",
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-fail", action="store_true")
    ap.add_argument("--theme", default=None, help="restrict to one theme id")
    args = ap.parse_args()

    themes = [args.theme] if args.theme else list_theme_ids()
    all_rows = []
    for t in themes:
        all_rows.extend(evaluate(t))

    n_pass = sum(1 for r in all_rows if r["status"] == "PASS")
    n_fail = sum(1 for r in all_rows if r["status"] == "FAIL")
    n_cne = sum(1 for r in all_rows if r["status"] == "COULD_NOT_EVALUATE")

    for r in all_rows:
        if args.only_fail and r["status"] == "PASS":
            continue
        ratio_s = f"{r['ratio']:.2f}" if r["ratio"] is not None else "n/a"
        print(f"{r['status']:20s} {r['theme']:16s} {r['pairing']:28s} "
              f"ratio={ratio_s:>5s} need={r['threshold']:.1f} {r['detail']}")

    print(f"\n{len(themes)} themes, {len(all_rows)} pairings evaluated: "
          f"{n_pass} pass, {n_fail} fail, {n_cne} could-not-evaluate")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

from lib_pixel_measure import parse_color

BORDER_OFFSET = 0
BAND_OFFSETS = (1, 2, 3)
SAME_TOL = 6
DIFF_TOL = 20


def chan_delta(a: tuple, b: tuple) -> int:
    return max(abs(int(a[i]) - int(b[i])) for i in range(3))


def opaque(css_color: str) -> tuple:
    r, g, b, a = parse_color(css_color)
    if a < 0.999:
        raise RuntimeError(
            "token %r is translucent (alpha %.3f); a screenshot pixel cannot be "
            "compared against it without modelling the backdrop" % (css_color, a)
        )
    return (round(r), round(g), round(b))


def check_symmetry(m: dict, rows: tuple, failures: list) -> None:
    for rid, label in rows:
        row = m["rows"][rid]
        for off in BAND_OFFSETS:
            lp, rp = row["left"][off], row["right"][off]
            d = chan_delta(lp, rp)
            if d > SAME_TOL:
                failures.append(
                    "%s/%s: the pixel %d in from the LEFT edge is %s but %d in from "
                    "the RIGHT edge is %s (delta %d). Something is still painting a "
                    "left-side bar. computed box-shadow: %s"
                    % (m["theme"], label, off, lp, off, rp, d, row["boxShadow"]))


def check_control(m: dict, control: tuple, failures: list,
                  undetermined: list) -> None:
    row = m["rows"][control[0]]
    seen = max(chan_delta(row["left"][off], row["right"][off])
               for off in BAND_OFFSETS)
    if seen < DIFF_TOL:
        undetermined.append(
            "%s: the positive control paints a 3px rail on purpose and the sampler "
            "read its left and right bands as the same colour (max delta %d). The "
            "sampler is not measuring what it claims, so every other row's verdict "
            "in this theme is unproven" % (m["theme"], seen))


def check_border_is_theme(m: dict, rows: tuple, failures: list,
                          undetermined: list) -> None:
    try:
        want = opaque(m["tokens"]["border"])
    except RuntimeError as exc:
        undetermined.append("%s: %s" % (m["theme"], exc))
        return
    for rid, label in rows:
        if rid == "row-active":
            continue
        row = m["rows"][rid]
        for side in ("left", "right"):
            px = row[side][BORDER_OFFSET]
            d = chan_delta(px, want)
            if d > SAME_TOL:
                failures.append(
                    "%s/%s: the %s BORDER pixel is %s but --color-border is %s "
                    "(delta %d). The row is not carrying the theme's ring."
                    % (m["theme"], label, side, px, want, d))
        d_top = chan_delta(row["top"], want)
        if d_top > SAME_TOL:
            failures.append(
                "%s/%s: the TOP border pixel is %s but --color-border is %s "
                "(delta %d), so the ring is not on all four sides"
                % (m["theme"], label, row["top"], want, d_top))


def check_active_distinct(m: dict, failures: list) -> None:
    plain, active = m["rows"]["row-plain"], m["rows"]["row-active"]
    d_border = chan_delta(active["left"][BORDER_OFFSET], plain["left"][BORDER_OFFSET])
    if d_border < DIFF_TOL:
        failures.append(
            "%s: the ACTIVE row's border pixel %s is indistinguishable from the "
            "plain row's %s (delta %d) - the current session lost its accent ring"
            % (m["theme"], active["left"][BORDER_OFFSET],
               plain["left"][BORDER_OFFSET], d_border))
    d_fill = chan_delta(active["left"][3], plain["left"][3])
    if d_fill < DIFF_TOL:
        failures.append(
            "%s: the ACTIVE row's fill pixel %s is indistinguishable from the plain "
            "row's %s (delta %d) - the accent background is not painting"
            % (m["theme"], active["left"][3], plain["left"][3], d_fill))


def check_pinned_is_plain(m: dict, failures: list) -> None:
    plain, pinned = m["rows"]["row-plain"], m["rows"]["row-pinned"]
    for off in (BORDER_OFFSET,) + BAND_OFFSETS:
        d = chan_delta(pinned["left"][off], plain["left"][off])
        if d > SAME_TOL:
            failures.append(
                "%s: the PINNED row's pixel %d in from the left is %s against the "
                "plain row's %s (delta %d) - a pinned rail is still painting"
                % (m["theme"], off, pinned["left"][off], plain["left"][off], d))


def check_identity_survives(m: dict, failures: list) -> None:
    plain, themed = m["rows"]["row-plain"], m["rows"]["row-themed"]
    if plain.get("swatch_px") is not None:
        failures.append(
            "%s: the UNTHEMED row is carrying a theme swatch - the cue must mean "
            "'this session has its own theme' and nothing else" % m["theme"])
    px = themed.get("swatch_px")
    if px is None:
        failures.append(
            "%s: the session-themed row has no swatch, and nothing on its edges "
            "either - session identity is not on screen at all" % m["theme"])
        return
    d = chan_delta(px, themed["left"][1])
    if d < DIFF_TOL:
        failures.append(
            "%s: the session-themed row's swatch pixel %s is indistinguishable "
            "from the row behind it %s (delta %d) - the swatch is rendering, but "
            "invisibly" % (m["theme"], px, themed["left"][1], d))


def check_cross_theme(a: dict, b: dict, rows: tuple, failures: list) -> None:
    for rid, label in rows:
        pa = a["rows"][rid]["left"][BORDER_OFFSET]
        pb = b["rows"][rid]["left"][BORDER_OFFSET]
        if chan_delta(pa, pb) < DIFF_TOL:
            failures.append(
                "%s: the border pixel is %s under %s and %s under %s - it did not "
                "follow the theme change, so matching one theme's token was a "
                "coincidence" % (label, pa, a["theme"], pb, b["theme"]))

#!/usr/bin/env python3
"""The verdicts scripts/verify_session_theme_carrier.py reaches about a row.

Split out so neither file grows past this project's 500-line ceiling. WHY
each check is the check it is lives in that script's module docstring;
what lives here is only how each one is measured.

Every function takes an already-sampled bundle and appends to `failures`
or `undetermined`. None of them sample anything, so none can disagree
with the sampler about what was measured - there is one sampler and these
read its output.

The split between the two lists is the THREE-OUTCOME RULE: `failures`
means something was measured and was wrong, `undetermined` means the
measurement could not be taken and no verdict is available. A
could-not-evaluate is never appended to `failures`, and never dropped.
"""

from __future__ import annotations

from lib_pixel_measure import parse_color

SAME_TOL = 6
DIFF_TOL = 20


def chan_delta(a, b) -> int:
    return max(abs(int(a[i]) - int(b[i])) for i in range(3))


def opaque(css_color: str) -> tuple:
    r, g, b, a = parse_color(css_color)
    if a < 0.999:
        raise RuntimeError(
            "token %r is translucent (alpha %.3f); a screenshot pixel cannot be "
            "compared against it without modelling the backdrop" % (css_color, a))
    return (round(r), round(g), round(b))


def check_control(m: dict, undetermined: list) -> bool:
    """The sampler must be able to SEE the accent, or nothing else counts.

    Almost every verdict in this run is "this pixel is not the accent".
    A blind sampler satisfies all of them while measuring nothing, which
    is a false green generated inside the verification step.

    Inputs: m (dict) - one measure_theme bundle; undetermined (list).
    Output: bool - True when the control was seen and the rest may run.
    """
    try:
        want = opaque(m["tokens"]["accent"])
    except (RuntimeError, ValueError) as exc:
        undetermined.append("%s: --color-accent unusable: %s" % (m["theme"], exc))
        return False
    got = tuple(m["rows"]["control-accent"]["fill"])
    d = chan_delta(got, want)
    if d > SAME_TOL:
        undetermined.append(
            "%s: POSITIVE CONTROL FAILED - a row painted --color-accent %s sampled "
            "as %s (delta %d). The sampler cannot see this colour, so every 'this "
            "is not the accent' verdict in this theme is unproven, not passing."
            % (m["theme"], want, got, d))
        return False
    return True


def check_both_directions(m: dict, offsets, failures: list) -> None:
    theme = m["theme"]
    plain = m["rows"]["row-plain"]
    themed = m["rows"]["row-themed"]
    active = m["rows"]["row-active"]

    for side in ("left", "right"):
        for off in offsets:
            d = chan_delta(themed[side][off], plain[side][off])
            if d > SAME_TOL:
                failures.append(
                    "%s: the themed row's pixel %d in from the %s edge is %s "
                    "against the plain row's %s (delta %d). The session tint is "
                    "still painting the row's edge, which is the channel "
                    "selection owns. computed box-shadow: %s"
                    % (theme, off, side, tuple(themed[side][off]),
                       tuple(plain[side][off]), d, themed["boxShadow"]))
    d_fill = chan_delta(themed["fill"], plain["fill"])
    if d_fill > SAME_TOL:
        failures.append(
            "%s: the themed row's FILL pixel is %s against the plain row's %s "
            "(delta %d). The session tint is still painting the row background, "
            "which is the channel selection owns. computed background-image: %s"
            % (theme, tuple(themed["fill"]), tuple(plain["fill"]), d_fill,
               themed["backgroundImage"]))

    d_border = chan_delta(active["left"][0], plain["left"][0])
    if d_border < DIFF_TOL:
        failures.append(
            "%s: the SELECTED row's border pixel %s is indistinguishable from the "
            "plain row's %s (delta %d) - selection lost its accent ring"
            % (theme, tuple(active["left"][0]), tuple(plain["left"][0]), d_border))
    d_abg = chan_delta(active["fill"], plain["fill"])
    if d_abg < DIFF_TOL:
        failures.append(
            "%s: the SELECTED row's fill pixel %s is indistinguishable from the "
            "plain row's %s (delta %d) - selection lost its accent background"
            % (theme, tuple(active["fill"]), tuple(plain["fill"]), d_abg))

    seen = max(chan_delta(themed[side][off], active[side][off])
               for side in ("left", "right") for off in offsets)
    seen = max(seen, chan_delta(themed["fill"], active["fill"]))
    if seen < DIFF_TOL:
        failures.append(
            "%s: a THEMED, NOT-SELECTED row and a SELECTED row are the same colour "
            "everywhere sampled (max delta %d). This is the reported bug: a themed "
            "row reads as the session you are in." % (theme, seen))


def check_identity_carrier(m: dict, failures: list) -> None:
    theme = m["theme"]
    for rid in ("row-plain", "row-active", "home-plain"):
        if m["rows"][rid].get("swatch"):
            failures.append(
                "%s/%s: an UNTHEMED row is carrying a theme swatch - the cue must "
                "mean 'this session has its own theme' and nothing else"
                % (theme, rid))

    try:
        want = opaque(m["sessionAccent"])
    except (RuntimeError, ValueError):
        return
    for rid in ("row-themed", "row-active-themed", "home-themed"):
        row = m["rows"][rid]
        sw = row.get("swatch")
        if not sw:
            failures.append(
                "%s/%s: a themed row has NO swatch element - session identity is "
                "not on screen at all" % (theme, rid))
            continue
        if sw["rect"]["w"] < 8 or sw["rect"]["h"] < 8:
            failures.append(
                "%s/%s: the swatch lays out %dx%d at density %s, which is not a "
                "visible mark" % (theme, rid, sw["rect"]["w"], sw["rect"]["h"],
                                  m.get("density")))
            continue
        box, rowbox = sw["rect"], row["rect"]
        if (box["y"] < rowbox["y"]
                or box["y"] + box["h"] > rowbox["y"] + rowbox["h"]
                or box["x"] + box["w"] > rowbox["x"] + rowbox["w"]):
            failures.append(
                "%s/%s: the swatch box (%d,%d %dx%d) is not contained by its row "
                "(%d,%d %dx%d) at density %s"
                % (theme, rid, box["x"], box["y"], box["w"], box["h"],
                   rowbox["x"], rowbox["y"], rowbox["w"], rowbox["h"],
                   m.get("density")))
        got = tuple(row["swatch_fill"])
        d = chan_delta(got, want)
        if d > SAME_TOL:
            failures.append(
                "%s/%s: the swatch PIXEL is %s but the session accent is %s "
                "(delta %d) - the mark is not the session's colour"
                % (theme, rid, got, want, d))
        edge = tuple(row["swatch_edge"])
        if chan_delta(edge, got) < DIFF_TOL:
            failures.append(
                "%s/%s: the swatch's edge pixel %s is the same colour as its fill "
                "%s - it has no hairline, so a session accent close to the row "
                "background renders an invisible swatch"
                % (theme, rid, edge, got))
        if not sw["ariaLabel"].strip():
            failures.append(
                "%s/%s: the swatch has no accessible name, so the cue is "
                "colour-only" % (theme, rid))


def check_launchpad_matches_sidebar(m: dict, offsets, failures: list) -> None:
    theme = m["theme"]
    plain = m["rows"]["home-plain"]
    themed = m["rows"]["home-themed"]
    for side in ("left", "right"):
        for off in offsets:
            d = chan_delta(themed[side][off], plain[side][off])
            if d > SAME_TOL:
                failures.append(
                    "%s: the HOME themed row's pixel %d in from the %s edge is %s "
                    "against the unthemed home row's %s (delta %d). The tint still "
                    "paints the home row's edge. computed box-shadow: %s"
                    % (theme, off, side, tuple(themed[side][off]),
                       tuple(plain[side][off]), d, themed["boxShadow"]))

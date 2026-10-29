from __future__ import annotations

import json
import math
import re
from pathlib import Path

from tests.helpers.guard_fold import assert_no_offenders

REPO = Path(__file__).resolve().parents[1]
TOKENS_CSS = REPO / "web" / "src" / "opscenter" / "tokens.css"
RULE_CSS = REPO / "client" / "css" / "scrollbars.css"
INDEX_HTML = REPO / "client" / "index.html"
THEMES = REPO / "client" / "css" / "themes"

MIN_THUMB_TRACK_RATIO = 2.0



def _srgb_to_linear(u: float) -> float:
    return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return 12.92 * u if u <= 0.0031308 else 1.055 * (u ** (1 / 2.4)) - 0.055


def parse_color(value: str, over: tuple[float, float, float] | None = None
                ) -> tuple[float, float, float]:
    text = value.strip()
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        if len(digits) == 8:
            digits = digits[:6]
        if len(digits) != 6:
            raise ValueError(f"not a hex colour: {value!r}")
        return tuple(int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
    if text.startswith("rgb"):
        parts = [p.strip() for p in text[text.index("(") + 1:text.index(")")].replace("/", ",").split(",")]
        rgb = [float(p) / 255 for p in parts[:3]]
        if len(parts) > 3 and over is not None:
            alpha = float(parts[3])
            return tuple(rgb[i] * alpha + over[i] * (1 - alpha) for i in range(3))  # type: ignore[return-value]
        return tuple(rgb)  # type: ignore[return-value]
    raise ValueError(f"unsupported colour form: {value!r}")


def to_oklab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def from_oklab(lab: tuple[float, float, float]) -> tuple[float, float, float]:
    big_l, a, b = lab
    l_ = big_l + 0.3963377774 * a + 0.2158037573 * b
    m_ = big_l - 0.1055613458 * a - 0.0638541728 * b
    s_ = big_l - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = (v ** 3 for v in (l_, m_, s_))
    return (
        _linear_to_srgb(+4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
        _linear_to_srgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
        _linear_to_srgb(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s),
    )


def color_mix_oklab(first: tuple[float, float, float],
                    second: tuple[float, float, float],
                    first_pct: float) -> tuple[float, float, float]:
    a, b = to_oklab(first), to_oklab(second)
    p = first_pct / 100.0
    return from_oklab(tuple(a[i] * p + b[i] * (1 - p) for i in range(3)))  # type: ignore[arg-type]


def relative_luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(one: tuple[float, float, float],
                   other: tuple[float, float, float]) -> float:
    a, b = relative_luminance(one), relative_luminance(other)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def to_hex(rgb: tuple[float, float, float]) -> str:
    return "#%02x%02x%02x" % tuple(int(round(max(0.0, min(1.0, c)) * 255)) for c in rgb)



_MIX_RE = re.compile(
    r"--oc-scrollbar-(?P<name>thumb|thumb-hover|track)\s*:\s*"
    r"color-mix\(\s*in\s+oklab\s*,\s*var\(\s*(?P<source>--[\w-]+)\s*\)\s*"
    r"(?P<pct>\d+(?:\.\d+)?)%\s*,\s*var\(\s*(?P<ground>--[\w-]+)\s*\)\s*\)"
)


def _declarations() -> dict[str, tuple[str, float, str]]:
    css = TOKENS_CSS.read_text(encoding="utf-8")
    return {
        m.group("name"): (m.group("source"), float(m.group("pct")), m.group("ground"))
        for m in _MIX_RE.finditer(css)
    }


def _theme_vars(theme_id: str) -> dict[str, str]:
    return json.loads((THEMES / theme_id / "theme.json").read_text(encoding="utf-8"))["cssVars"]


def _resolved(theme_id: str) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    decls = _declarations()
    css_vars = _theme_vars(theme_id)
    ground = parse_color(css_vars["--color-bg"])
    accent = parse_color(css_vars["--color-accent"], over=ground)
    text = parse_color(css_vars["--color-fg"], over=ground)
    thumb = color_mix_oklab(accent, ground, decls["thumb"][1])
    track = color_mix_oklab(text, ground, decls["track"][1])
    return accent, thumb, track


def _shipped_theme_ids() -> list[str]:
    ids = sorted(d.name for d in THEMES.iterdir() if (d / "theme.json").is_file())
    assert len(ids) >= 12, f"only {len(ids)} theme manifests found; the walk is wrong"
    return ids



def test_thumb_and_track_are_derived_from_the_theme_not_from_a_literal():
    decls = _declarations()
    assert "thumb" in decls, (
        "--oc-scrollbar-thumb is not a color-mix of an accent token onto a ground "
        "token in tokens.css. A literal thumb colour is the regression: it would "
        "be a red stripe down the side of the matrix theme."
    )
    assert "track" in decls
    assert "thumb-hover" in decls

    source, pct, ground = decls["thumb"]
    assert source == "--oc-orange", f"the thumb must come from the accent token, got {source}"
    assert ground == "--oc-ground-panel", f"the thumb must be mixed onto the ground, got {ground}"
    assert 50.0 <= pct <= 90.0, (
        f"the thumb mix is {pct}% of the accent. Below 50 it collapses into the "
        "ground on a dark theme; above 90 it is just the accent and stops "
        "reading as the darkened indicator that was asked for."
    )

    assert decls["thumb-hover"][1] > pct, "hover must move the thumb TOWARD the accent, not away"


def test_the_active_state_is_the_accent_itself():
    css = TOKENS_CSS.read_text(encoding="utf-8")
    assert re.search(r"--oc-scrollbar-thumb-active\s*:\s*var\(\s*--oc-orange\s*\)", css), (
        "holding the thumb should take it all the way to the theme's accent"
    )



def test_carnivore_resolves_the_thumb_to_a_dark_red():
    accent, thumb, _track = _resolved("carnivore")
    red, green, blue = thumb
    readable = to_hex(thumb)

    assert red > green and red > blue, f"carnivore's thumb {readable} is not red"
    assert red - max(green, blue) > 0.25, (
        f"carnivore's thumb {readable} is red only marginally; it should read as red"
    )
    assert relative_luminance(thumb) < relative_luminance(accent), (
        f"carnivore's thumb {readable} is not DARKER than its accent "
        f"{to_hex(accent)}; 'dark red' is the whole request"
    )
    assert relative_luminance(thumb) < 0.25, (
        f"carnivore's thumb {readable} is a bright red, not a dark one"
    )


def test_carnivore_thumb_stays_visible_against_its_own_track():
    _accent, thumb, track = _resolved("carnivore")
    ratio = contrast_ratio(thumb, track)
    assert ratio >= MIN_THUMB_TRACK_RATIO, (
        f"carnivore's thumb {to_hex(thumb)} against its track {to_hex(track)} is "
        f"{ratio:.2f}:1; a scrollbar nobody can see is not a scrollbar"
    )



def _check_every_shipped_theme_keeps_the_thumb_off_its_track(theme_id: str):
    _accent, thumb, track = _resolved(theme_id)
    ratio = contrast_ratio(thumb, track)
    assert ratio >= MIN_THUMB_TRACK_RATIO, (
        f"{theme_id}: thumb {to_hex(thumb)} against track {to_hex(track)} is only "
        f"{ratio:.2f}:1. Either that theme's accent is too close to its ground, or "
        f"the mix percentage moved."
    )


def test_every_shipped_theme_keeps_the_thumb_off_its_track() -> None:
    assert_no_offenders(
        "every shipped theme keeps the thumb off its track",
        _shipped_theme_ids(),
        _check_every_shipped_theme_keeps_the_thumb_off_its_track,
    )


def test_the_light_theme_darkens_rather_than_disappears():
    accent, thumb, track = _resolved("carnivore-light")
    assert relative_luminance(parse_color(_theme_vars("carnivore-light")["--color-bg"])) > 0.5, (
        "carnivore-light stopped being the light theme; pick a different one for this test"
    )
    assert contrast_ratio(thumb, track) >= MIN_THUMB_TRACK_RATIO
    assert to_hex(thumb) != to_hex(accent)



def test_the_rule_file_is_linked_and_paints_from_the_token():
    assert RULE_CSS.is_file(), "client/css/scrollbars.css is missing"
    assert "/static/css/scrollbars.css" in INDEX_HTML.read_text(encoding="utf-8"), (
        "the skin is not linked from client/index.html, so nothing loads it"
    )
    css = RULE_CSS.read_text(encoding="utf-8")
    assert "::-webkit-scrollbar-thumb" in css
    assert "var(--oc-scrollbar-thumb-rest)" in css
    assert "var(--oc-scrollbar-track)" in css
    assert "var(--oc-scrollbar-thumb-hover)" in css
    assert "var(--oc-scrollbar-thumb-active)" in css


def test_the_thumb_has_a_minimum_length_and_no_gutter_is_reserved():
    css = re.sub(r"/\*.*?\*/", "", RULE_CSS.read_text(encoding="utf-8"), flags=re.S)
    assert re.search(r"min-height:\s*var\(--scrollbar-thumb-min\)", css), (
        "without a minimum length a long list produces a two pixel thumb"
    )
    floor = re.search(r"--scrollbar-thumb-min:\s*(\d+)px", css)
    assert floor is not None, "the minimum thumb length token is missing"
    assert int(floor.group(1)) >= 24
    assert "scrollbar-gutter" not in css, (
        "a reserved gutter steals width on a phone that has no bar to put in it"
    )
    assert not re.search(r"display\s*:\s*none", css), (
        "this skin never hides a scrollbar; the thumb has to stay grabbable"
    )


def test_the_skin_is_gated_to_a_pointer_that_can_grab_a_thumb():
    css = re.sub(r"/\*.*?\*/", "", RULE_CSS.read_text(encoding="utf-8"), flags=re.S)
    gate = "@media (hover: hover) and (pointer: fine)"
    assert gate in css, "the skin must not paint a bar on a coarse pointer"
    after = css[css.index(gate):]
    for pseudo in ("::-webkit-scrollbar", "scrollbar-color:", "scrollbar-width:"):
        assert css.count(pseudo) == after.count(pseudo), (
            f"{pseudo} is declared OUTSIDE the pointer gate, so a phone pays "
            "11px of width for a scrollbar it cannot use"
        )


def test_the_two_mechanisms_are_not_both_switched_on():
    css = RULE_CSS.read_text(encoding="utf-8")
    guard = "@supports not selector(::-webkit-scrollbar)"
    assert guard in css, "the standard properties need the no-pseudo-elements guard"
    body = css[css.index(guard):]
    for prop in ("scrollbar-color:", "scrollbar-width:"):
        assert prop in body, f"{prop} is missing from the guarded block"
        assert css.count(prop) == body.count(prop), (
            f"{prop} is also declared OUTSIDE the guard, which disarms every "
            "::-webkit-scrollbar rule in this file"
        )


def test_the_rule_file_holds_no_colour_literal():
    css = RULE_CSS.read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    offenders = re.findall(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(", stripped)
    assert not offenders, f"colour literals in client/css/scrollbars.css: {offenders}"


def test_the_terminal_viewport_is_not_restyled_here():
    css = RULE_CSS.read_text(encoding="utf-8")
    assert ".xterm" not in re.sub(r"/\*.*?\*/", "", css, flags=re.S), (
        "this file must not carry an xterm rule; the opt-out lives in styles.css"
    )
    styles = (REPO / "client" / "css" / "styles.css").read_text(encoding="utf-8")
    assert ".xterm-host .xterm-viewport::-webkit-scrollbar" in styles, (
        "the emulator opt-out disappeared; every terminal would grow a bar and "
        "xterm's column measurement would shift under it"
    )

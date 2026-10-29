
from __future__ import annotations

import json
import re
from pathlib import Path

from tests.helpers.guard_fold import assert_no_offenders

ROOT = Path(__file__).resolve().parents[1]
THEMES_DIR = ROOT / "client" / "css" / "themes"
STYLES = ROOT / "client" / "css" / "styles.css"

BODY_TOKENS = ("--color-fg", "--color-fg-muted")

INCIDENTAL_TOKENS = ("--color-fg-subtle", "--color-fg-faint")

AA_BODY = 4.5
AA_LARGE = 3.0

KNOWN_NEAR_MISSES: dict = {}

NEAR_MISS_SLACK = 0.5


def _theme_dirs() -> list[Path]:
    return sorted(p for p in THEMES_DIR.iterdir()
                  if p.is_dir() and (p / "theme.json").is_file())


def _theme(name_dir: Path) -> dict:
    return json.loads((name_dir / "theme.json").read_text(encoding="utf-8"))


def _root_defaults() -> dict[str, str]:
    text = STYLES.read_text(encoding="utf-8")
    start = text.index(":root {")
    end = text.index("\n}", start)
    block = text[start:end]
    return dict(re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", block))


def _luminance(hex_color: str) -> float:
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _resolve(theme_vars: dict, defaults: dict, token: str) -> str | None:
    value = theme_vars.get(token, defaults.get(token, "")).strip()
    return value if re.fullmatch(r"#[0-9a-fA-F]{3,8}", value) else None



def test_the_theme_loader_finds_themes() -> None:
    dirs = _theme_dirs()
    assert len(dirs) >= 12, f"only {len(dirs)} themes found; the loader is broken"
    names = {d.name for d in dirs}
    assert {"carnivore", "carnivore-light", "matrix", "black_ops"} <= names


def test_the_contrast_function_can_return_a_failing_number() -> None:
    assert round(_contrast("#000000", "#ffffff"), 1) == 21.0
    assert round(_contrast("#777777", "#777777"), 2) == 1.0
    assert round(_contrast("#000000", "#0a0a0a"), 2) == 1.06


def test_the_root_defaults_parse() -> None:
    defaults = _root_defaults()
    assert defaults.get("--color-bg-page") == "#0a0a0a"
    assert defaults.get("--color-fg") == "#d4d4d4"



def _check_theme_declares_bg_page(theme_dir: Path) -> None:
    css_vars = _theme(theme_dir).get("cssVars", {})
    assert "--color-bg-page" in css_vars, (
        f"{theme_dir.name} does not declare --color-bg-page, so it renders the "
        "global default from styles.css. That is a real colour tuned for the "
        "dark Claude palette; on a light theme it is black text on near-black. "
        "It is also invisible in the theme file, which is why legacy_windows "
        "sat at 1.06:1 until the archive painted this token full-screen."
    )


def test_theme_declares_bg_page() -> None:
    assert_no_offenders(
        "theme declares bg page",
        _theme_dirs(),
        _check_theme_declares_bg_page,
        label=lambda p: p.name,
    )


def _check_body_text_is_legible_on_the_page_surface(theme_dir: Path) -> None:
    defaults = _root_defaults()
    css_vars = _theme(theme_dir).get("cssVars", {})
    page = _resolve(css_vars, defaults, "--color-bg-page")
    assert page is not None, f"{theme_dir.name} has a non-hex --color-bg-page"
    for token in BODY_TOKENS:
        fg = _resolve(css_vars, defaults, token)
        if fg is None:
            continue
        ratio = _contrast(fg, page)
        if (theme_dir.name, token) in KNOWN_NEAR_MISSES:
            assert ratio < AA_BODY, (
                f"{theme_dir.name}: {token} now measures {ratio:.2f}:1 and "
                f"PASSES. Delete its entry from KNOWN_NEAR_MISSES - a "
                "documented exception for a fixed problem is a lie the next "
                "reader will believe."
            )
            assert ratio >= AA_BODY - NEAR_MISS_SLACK, (
                f"{theme_dir.name}: {token} measures {ratio:.2f}:1, which is "
                f"more than {NEAR_MISS_SLACK} below AA. This is no longer the "
                "documented near-miss; it is a regression hiding behind one."
            )
            continue
        assert ratio >= AA_BODY, (
            f"{theme_dir.name}: {token} ({fg}) on --color-bg-page ({page}) "
            f"measures {ratio:.2f}:1, below the {AA_BODY}:1 WCAG AA floor for "
            "body text. The archive paints this surface full-viewport."
        )


def test_body_text_is_legible_on_the_page_surface() -> None:
    assert_no_offenders(
        "body text is legible on the page surface",
        _theme_dirs(),
        _check_body_text_is_legible_on_the_page_surface,
        label=lambda p: p.name,
    )


def _check_incidental_text_clears_the_large_text_floor(theme_dir: Path) -> None:
    defaults = _root_defaults()
    css_vars = _theme(theme_dir).get("cssVars", {})
    page = _resolve(css_vars, defaults, "--color-bg-page")
    assert page is not None
    for token in INCIDENTAL_TOKENS:
        fg = _resolve(css_vars, defaults, token)
        if fg is None:
            continue
        ratio = _contrast(fg, page)
        assert ratio >= AA_LARGE, (
            f"{theme_dir.name}: {token} ({fg}) on --color-bg-page ({page}) "
            f"measures {ratio:.2f}:1, below the {AA_LARGE}:1 floor even for "
            "incidental text."
        )


def test_incidental_text_clears_the_large_text_floor() -> None:
    assert_no_offenders(
        "incidental text clears the large text floor",
        _theme_dirs(),
        _check_incidental_text_clears_the_large_text_floor,
        label=lambda p: p.name,
    )


def test_the_near_miss_list_names_only_real_themes_and_real_tokens() -> None:
    names = {d.name for d in _theme_dirs()}
    defaults = _root_defaults()
    for (theme, token) in KNOWN_NEAR_MISSES:
        assert theme in names, f"KNOWN_NEAR_MISSES names a theme that is gone: {theme}"
        assert token in BODY_TOKENS or token in INCIDENTAL_TOKENS, (
            f"KNOWN_NEAR_MISSES names a token this suite does not check: {token}")
        css_vars = _theme(THEMES_DIR / theme).get("cssVars", {})
        assert _resolve(css_vars, defaults, token) is not None, (
            f"{theme} no longer defines a hex {token}")

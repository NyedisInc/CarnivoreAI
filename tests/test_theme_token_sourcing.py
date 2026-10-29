from __future__ import annotations

import re
from pathlib import Path

STYLES_CSS = Path(__file__).resolve().parents[1] / "client" / "css" / "styles.css"

_LITERAL_COLOR_RE = re.compile(
    r"(?:color|background)\s*:\s*(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|"
    r"\b(?:blue|red|green|yellow|purple|orange|pink|cyan|magenta)\b)",
    re.IGNORECASE,
)


def _rule_body(css: str, selector: str) -> str:
    idx = css.index(selector)
    start = css.index("{", idx)
    end = css.index("}", start)
    return css[start + 1:end]


def test_ownership_stripe_is_gone_entirely():
    css = STYLES_CSS.read_text(encoding="utf-8")
    for selector in (".running-session-row.owned", ".running-session-row.external"):
        for line in css.splitlines():
            stripped = line.strip()
            if stripped.startswith(selector) and "{" in stripped:
                raise AssertionError(
                    f"{selector} has a paint rule again. Session type is carried "
                    "by the TMUX / EXTERNAL badge; a coloured left edge is a "
                    "second source of truth for it and was removed on request."
                )


def test_session_row_border_is_one_theme_token_on_all_four_sides():
    css = STYLES_CSS.read_text(encoding="utf-8")
    body = _rule_body(css, ".running-session-row {")
    assert re.search(r"border:\s*1px solid var\(--color-border\)", body), (
        ".running-session-row must declare ONE border, from --color-border, on "
        "all four sides - the same ring .project-item already uses"
    )
    assert not re.search(r"border-left\s*:", body), (
        "a border-left override here re-creates the single-coloured-edge shape "
        "this change removed"
    )
    literal = _LITERAL_COLOR_RE.search(body)
    assert literal is None, (
        f".running-session-row has a hardcoded color ({literal.group(0)!r}); the "
        "border and background must both resolve from theme tokens"
    )


def test_help_readme_link_is_themed_not_default_blue():
    css = STYLES_CSS.read_text(encoding="utf-8")
    assert ".adopt-disclosure-body a" in css, (
        "no rule targets the README link at all - it will render the browser's "
        "default blue/purple link color in every theme"
    )
    body = _rule_body(css, ".adopt-disclosure-body a {")
    literal = _LITERAL_COLOR_RE.search(body)
    assert literal is None, (
        f".adopt-disclosure-body a has a hardcoded color ({literal.group(0)!r}) "
        "instead of a var(--color-accent*) token"
    )
    assert "var(--color-accent" in body

    assert "text-decoration: underline" in body, (
        ".adopt-disclosure-body a has no at-rest underline - color is the "
        "only thing distinguishing it from surrounding body text"
    )


def test_no_other_hardcoded_link_colors_in_styles_css():
    css = STYLES_CSS.read_text(encoding="utf-8")
    anchor_rule_re = re.compile(r"([.\w#:>\s,-]*\ba(?::hover|:visited|:focus-visible|:focus)?\s*\{[^}]*\})")
    offenders = []
    for m in anchor_rule_re.finditer(css):
        rule = m.group(1)
        selector = rule.split("{", 1)[0]
        if not re.search(r"(^|[\s>.,])a(:\w[\w-]*)?\s*$", selector.strip()):
            continue
        literal = _LITERAL_COLOR_RE.search(rule)
        if literal:
            offenders.append((selector.strip(), literal.group(0)))
    assert not offenders, f"hardcoded link color(s) found: {offenders}"

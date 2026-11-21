from __future__ import annotations

import re
from pathlib import Path

from tests.python.design_system._sources import REPO, css_of, strip_comments, top_level_chunks

TOKENS = REPO / "web/src/opscenter/tokens.css"
LEDGER_CHROME = REPO / "web/src/lib/ledger/ledger-chrome.css"
SEARCH_PANEL = REPO / "web/src/lib/terminal-search/SearchPanel.svelte"
SCAN_ROOTS = (REPO / "web/src", REPO / "client/css")

DERIVED_SELECTOR = ":root, [data-session-theme]"

PL_ALIAS_READERS_KEPT = frozenset({
    "web/src/lib/ledger/ledger-chrome.css",
    "web/src/lib/skills-page/skills-page.css",
    "web/src/lib/computers/computers.css",
    "web/src/lib/pack-machines/pack-machines.css",
    "web/src/lib/pack-machines/pack-work.css",
    "web/src/lib/pack-migrate/migrate-wizard.css",
})

_DECL = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;{}]+);")
_LITERAL_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab|lab|lch|hwb)\(|\b(?:white|black)\b")
_THEME_ID_SELECTOR = re.compile(r'(:root)?\[data-(session-)?theme="([^"]+)"\]')
_BORDER_AS_COLOR = re.compile(
    r"\b(?:solid|dashed|dotted|double)\s+var\(--oc-border\)"
    r"|(?<![\w-])(?:color|background(?:-color)?|border(?:-[a-z]+)?-color|outline-color|fill|stroke)\s*:\s*var\(--oc-border\)"
)
_PL_READ = re.compile(r"var\(--pl-[a-z0-9-]+")
PHONE_MEDIA = "(max-width: 1023px)"


def frozen_derived_colors(css: str) -> list[str]:
    frozen: list[str] = []
    for chunk in top_level_chunks(css):
        selector = " ".join(chunk.split("{", 1)[0].split())
        if selector != DERIVED_SELECTOR:
            continue
        for name, value in _DECL.findall(chunk):
            value = value.strip()
            if _LITERAL_COLOR.search(value) and "var(" not in value:
                frozen.append(f"{name}: {value}")
    return frozen


def one_sided_theme_overrides(css: str) -> list[str]:
    sides: dict[str, set[str]] = {}
    for chunk in top_level_chunks(css):
        selector = chunk.split("{", 1)[0]
        for root, session, theme_id in _THEME_ID_SELECTOR.findall(selector):
            sides.setdefault(theme_id, set()).add("session" if session else ("global" if root else "bare"))
    return sorted(
        f"{theme_id}: only {', '.join(sorted(found))}"
        for theme_id, found in sides.items()
        if not {"session", "global"} <= found
    )


def literal_search_colors(svelte_text: str) -> list[str]:
    css = strip_comments("".join(re.findall(r"<style[^>]*>(.*?)</style>", svelte_text, re.S)))
    found = [(n, v.strip()) for n, v in _DECL.findall(css) if n.startswith("--terminal-search-")]
    return [f"{n}: {v}" for n, v in found if _LITERAL_COLOR.search(v) or "var(--oc-" not in v]


def border_width_used_as_color(css: str) -> int:
    return len(_BORDER_AS_COLOR.findall(css))


def reads_pl_alias(css: str) -> bool:
    return bool(_PL_READ.search(css))


def wide_and_phone_value(css: str, name: str) -> tuple[str | None, str | None]:
    wide: str | None = None
    phone: str | None = None
    for chunk in top_level_chunks(css):
        head = " ".join(chunk.split("{", 1)[0].split())
        found = [v.strip() for n, v in _DECL.findall(chunk) if n == name]
        if not found:
            continue
        if head.startswith("@media"):
            if PHONE_MEDIA in head:
                phone = found[-1]
        elif not head.startswith("@"):
            wide = found[-1]
    return wide, phone if phone is not None else wide


def _scanned_files() -> list[Path]:
    return sorted(
        p for root in SCAN_ROOTS for p in root.rglob("*")
        if p.suffix in {".css", ".svelte"} and "node_modules" not in p.parts
    )


def test_derived_palette_has_no_frozen_color() -> None:
    css = strip_comments(TOKENS.read_text())
    assert DERIVED_SELECTOR in " ".join(css.split()), "the derived palette block is gone; the scan would see nothing"
    frozen = frozen_derived_colors(css)
    assert not frozen, "derived palette colors no theme can move (derive them from a --color-* or --oc-* value):\n  " + (
        "\n  ".join(frozen))


def test_every_theme_override_reaches_global_and_session_paint() -> None:
    lopsided = one_sided_theme_overrides(strip_comments(TOKENS.read_text()))
    assert not lopsided, (
        'a theme override must name both `:root[data-theme="id"]` and `[data-session-theme="id"]`:\n  '
        + "\n  ".join(lopsided))


def test_terminal_search_highlights_read_tokens() -> None:
    text = SEARCH_PANEL.read_text()
    assert "--terminal-search-active-bg" in text, "the search highlight block moved; this check would see nothing"
    literal = literal_search_colors(text)
    assert not literal, "terminal search highlights a theme cannot move:\n  " + "\n  ".join(literal)


def test_border_width_token_is_never_a_color() -> None:
    files = _scanned_files()
    assert len(files) > 200, f"scanned only {len(files)} files; the walk is broken"
    offenders = [
        f"{p.relative_to(REPO)} x{n}" for p in files
        if (n := border_width_used_as_color(css_of(p) if p.suffix == ".svelte" else strip_comments(p.read_text())))
    ]
    assert not offenders, "var(--oc-border) is a width; a color slot drops the declaration:\n  " + "\n  ".join(offenders)


def test_pl_aliases_are_read_only_where_kept() -> None:
    readers = {
        str(p.relative_to(REPO)) for p in _scanned_files()
        if reads_pl_alias(css_of(p) if p.suffix == ".svelte" else strip_comments(p.read_text()))
    }
    assert readers & PL_ALIAS_READERS_KEPT, "no kept reader reads --pl-* any more; shrink PL_ALIAS_READERS_KEPT"
    stray = sorted(readers - PL_ALIAS_READERS_KEPT)
    assert not stray, "read the --oc-* token directly, not its --pl-* alias:\n  " + "\n  ".join(stray)
    gone = sorted(r for r in PL_ALIAS_READERS_KEPT if r not in readers)
    assert not gone, "these kept readers no longer read --pl-*; drop them from the list:\n  " + "\n  ".join(gone)


def test_region_gutter_token_is_as_responsive_as_the_alias_it_replaces() -> None:
    alias = wide_and_phone_value(strip_comments(LEDGER_CHROME.read_text()), "--pl-gutter")
    assert alias[0] is not None, "--pl-gutter left ledger-chrome.css; this check would compare nothing"
    token = wide_and_phone_value(strip_comments(TOKENS.read_text()), "--oc-region-gutter")
    assert token == alias, f"--oc-region-gutter (wide, phone) {token} must equal --pl-gutter's {alias}"
    assert token[0] != token[1], "--oc-region-gutter must narrow at the phone breakpoint"


def test_negative_control_each_rule_goes_red() -> None:
    assert frozen_derived_colors(":root,\n[data-session-theme] { --oc-a: #3f4649; --oc-b: var(--color-x, #fff); }") == [
        "--oc-a: #3f4649"]
    assert frozen_derived_colors(":root { --oc-a: #3f4649; }") == [], "only the derived block is the palette"
    assert one_sided_theme_overrides('[data-session-theme="x"] { --oc-a: red; }') == ["x: only session"]
    assert one_sided_theme_overrides(':root[data-theme="x"],\n[data-session-theme="x"] { --oc-a: red; }') == []
    planted = '<style>:global(.t) { --terminal-search-match-bg: #4d3b30; --terminal-search-active-bg: var(--oc-search-active-bg); }</style>'
    assert literal_search_colors(planted) == ["--terminal-search-match-bg: #4d3b30"]
    assert border_width_used_as_color(".a { border-top: 1px solid var(--oc-border); color: var(--oc-border) }") == 2
    assert border_width_used_as_color(".a { border: var(--oc-border) solid var(--oc-line-rule) }") == 0
    assert reads_pl_alias(".a { gap: var(--pl-gutter, 16px); }") is True
    assert reads_pl_alias(".a { gap: var(--oc-region-gutter); }") is False
    assert wide_and_phone_value(":root { --g: 16px; }", "--g") == ("16px", "16px"), "a fixed token reads one value"
    assert wide_and_phone_value(
        ":root { --g: 16px; } @media (max-width: 1023px) { :root { --g: 12px; } } @media (min-width: 701px) { :root { --g: 2px; } }",
        "--g") == ("16px", "12px")

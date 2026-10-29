from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CLIENT = REPO / "client"
CANONICAL = [
    "reset", "tokens", "base", "primitives", "patterns",
    "components", "pages", "utilities", "legacy", "overrides",
]
_LINK = re.compile(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"')
_ORDER = re.compile(r"@layer\s+([a-z, \-]+);")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def first_stylesheet(html: str) -> str:
    match = _LINK.search(re.sub(r"<!--.*?-->", "", html, flags=re.S))
    assert match, "no stylesheet link found; the reader is broken"
    return match.group(1)


def declared_order(css: str) -> list[str]:
    found = _ORDER.findall(_strip_comments(css))
    assert len(found) == 1, f"layers.css must hold exactly one @layer statement, found {len(found)}"
    return [name.strip() for name in found[0].split(",")]


def unlayered_universal_spacing(css: str) -> bool:
    text = _strip_comments(css)
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                prelude = text[start:i].strip()
                body_start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                body = text[body_start:i]
                if prelude == "*" and re.search(r"\b(margin|padding)\s*:", body):
                    return True
                start = i + 1
        elif ch == ";" and depth == 0:
            start = i + 1
    return False


@pytest.mark.parametrize("page", ["index.html", "style-guide.html"])
def test_layers_css_is_the_first_stylesheet(page: str) -> None:
    assert first_stylesheet((CLIENT / page).read_text(encoding="utf-8")) == "/static/css/layers.css"


def test_layers_css_declares_the_canonical_order_and_nothing_else() -> None:
    css = (CLIENT / "css" / "layers.css").read_text(encoding="utf-8")
    assert declared_order(css) == CANONICAL
    assert re.sub(r"@layer[^;]*;", "", _strip_comments(css)).strip() == ""


def test_the_global_reset_is_layered() -> None:
    offenders = [
        p.name for p in sorted((CLIENT / "css").glob("*.css"))
        if unlayered_universal_spacing(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"an unlayered `*` reset beats every layered padding and margin: {offenders}"
    styles = _strip_comments((CLIENT / "css" / "styles.css").read_text(encoding="utf-8"))
    assert re.search(r"@layer reset\s*\{\s*\*\s*\{[^}]*padding:\s*0", styles), "the reset must sit in @layer reset"


def test_the_shared_controls_use_only_canonical_layers_and_no_unlayered_rule() -> None:
    css = _strip_comments((REPO / "web/src/opscenter/controls.css").read_text(encoding="utf-8"))
    names = re.findall(r"@layer\s+([a-z-]+)\s*\{", css)
    assert names and set(names) <= {"primitives", "patterns"}, names
    depth, outside = 0, ""
    for ch in css:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            outside += ch
    leftover = re.sub(r"@layer\s+[a-z-]+\s*", "", outside).strip()
    assert leftover == "", f"a rule outside every layer in controls.css: {leftover[:80]!r}"



def test_negative_control_an_unlayered_reset_is_flagged() -> None:
    assert unlayered_universal_spacing("* { margin: 0; padding: 0; }")
    assert not unlayered_universal_spacing("@layer reset { * { margin: 0; padding: 0; } }")


def test_negative_control_a_stray_layer_name_is_flagged() -> None:
    with pytest.raises(AssertionError):
        declared_order("@layer a; @layer b;")
    assert declared_order("@layer foo, reset;") != CANONICAL

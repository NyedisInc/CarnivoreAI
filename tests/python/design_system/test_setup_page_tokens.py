
from __future__ import annotations

import re
from pathlib import Path

SETUP_HTML = Path(__file__).resolve().parents[3] / "client" / "setup.html"
_COMMENT = re.compile(r"<!--.*?-->|/\*.*?\*/", re.DOTALL)
_LITERAL = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b|\b(?:rgba?|hsla?|oklch|oklab|lab|lch)\(")
LAYERS_LINK = '<link rel="stylesheet" href="/static/css/layers.css"'
TOKENS_LINK = '<link rel="stylesheet" href="/static/dist/app.css"'


def colour_literals(source: str) -> list[str]:
    return _LITERAL.findall(_COMMENT.sub("", source))


def test_setup_html_holds_no_colour_literal() -> None:
    found = colour_literals(SETUP_HTML.read_text(encoding="utf-8"))
    assert not found, f"setup.html still has {len(found)} colour literals: {found}"


def test_setup_html_reads_tokens_and_loads_the_token_stylesheets() -> None:
    html = SETUP_HTML.read_text(encoding="utf-8")
    assert "var(--oc-" in html
    assert LAYERS_LINK in html and TOKENS_LINK in html
    assert html.index(LAYERS_LINK) < html.index(TOKENS_LINK), "layers.css must be the first stylesheet"


def test_the_literal_scan_goes_red_on_a_fixture() -> None:
    fixture = "<!-- #aabbcc --><style>a{color:#abc;b:rgba(1,2,3,.5);c:var(--oc-cyan);/* #fff */}</style>"
    assert colour_literals(fixture) == ["#abc", "rgba("]

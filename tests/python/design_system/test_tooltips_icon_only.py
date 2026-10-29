from __future__ import annotations

import re

from tests.python.design_system._sources import REPO

WEB = REPO / "web" / "src"
CLIENT = REPO / "client"

OWNER_PREFIXES = (
    "opscenter/viz/", "opscenter/widgets/", "lib/widgets-page/",
    "opscenter/cells/analytics/", "opscenter/layout-editor/",
    "lib/byoai/",
    "style-guide/",
)

TAG = re.compile(
    r"<([a-z][a-z0-9]*)\b((?:[^<>{}\"']|\"[^\"]*\"|'[^']*'|\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\})*)>",
    re.S,
)
TOOLTIP_ATTR = re.compile(r"(?<![\w:-])(?:title|data-tooltip)\s*=\s*(?!\"\"|'')")
HEADING_CLASS = re.compile(
    r"(?:__header|__heading|-heading|__title|-title|__headerrow"
    r"|[_-]name|[_-]label|[_-]subtitle|[_-]text|[_-]summary|[_-]description|[_-]desc|[_-]cwd|[_-]snip)$"
)
OBJ = re.compile(r"\{[^{}]*?\bclass:\s*['\"]([^'\"]+)['\"][^{}]*?\b(?:title|'data-tooltip')\s*:", re.S)
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def offenders(text: str) -> list[tuple[int, str]]:
    found = []
    for m in TAG.finditer(text):
        tag, attrs = m.group(1), m.group(2)
        if not TOOLTIP_ATTR.search(attrs):
            continue
        cls = re.search(r"class\s*=\s*\"([^\"]*)\"", attrs)
        tokens = cls.group(1).split() if cls else []
        heading = (
            tag in HEADING_TAGS
            or 'role="heading"' in attrs
            or any(HEADING_CLASS.search(t) for t in tokens)
        )
        if heading:
            found.append((text.count("\n", 0, m.start()) + 1, tag))
    for m in OBJ.finditer(text):
        if any(HEADING_CLASS.search(t) for t in m.group(1).split()) or "data-row-name" in m.group(0):
            found.append((text.count("\n", 0, m.start()) + 1, "attrs"))
    return found


def test_scan_can_go_red() -> None:
    assert offenders('<h2 class="x" title="open it">a</h2>') == [(1, "h2")]
    assert offenders('<button class="g__header" data-tooltip={t("k")}>a</button>') == [(1, "button")]
    assert offenders('<span class="ldp-title" title="t">a</span>') == [(1, "span")]
    assert offenders('<span class="row-name" title="Orchardco">Orchardco</span>') == [(1, "span")]
    assert offenders('<span data-row-name="a" class="session-sidebar-row-name" title="a">a</span>') == [(1, "span")]
    assert offenders("{ attrs: { class: 'row-subtitle', title: subtitle }, text: subtitle }") == [(1, "attrs")]
    assert offenders('<button class="pin" title="pin to top"><svg/></button>') == []
    assert offenders('<h2 class="x" title="">a</h2>') == []


def test_no_heading_carries_a_tooltip() -> None:
    bad = []
    for path in sorted(WEB.rglob("*.svelte")):
        rel = path.relative_to(WEB).as_posix()
        if rel.startswith(OWNER_PREFIXES):
            continue
        for line, tag in offenders(path.read_text()):
            bad.append(f"web/src/{rel}:{line} <{tag}>")
    for path in sorted((CLIENT / "js").rglob("*.js")) + [CLIENT / "index.html"]:
        if "vendor" in path.parts:
            continue
        for line, tag in offenders(path.read_text()):
            bad.append(f"{path.relative_to(REPO).as_posix()}:{line} <{tag}>")
    assert not bad, "a heading carries a tooltip (a tooltip only says what an icon-only control does):\n" + "\n".join(bad)


def test_cut_off_reveal_is_script_written_never_authored() -> None:
    assert offenders('<span class="row-name" use:truncatedTip={name}>{name}</span>') == []
    assert offenders('<span class="row-name" data-cut-off-reveal>{name}</span>') == []
    assert offenders('<span class="row-name" title={name}>{name}</span>') == [(1, "span")]
    reveal = (WEB / "lib" / "tooltip" / "cut-off-reveal.ts").read_text()
    assert "setAttribute('data-tooltip'" in reveal and "isClipped" in reveal


from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

SCAN_ROOTS = ("client/css", "web/src")

KNOWN: dict[str, int] = {}

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_STYLE_BLOCK = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL)

_WRAPPERS = (":global(", ":not(", ":is(", ":where(", ":matches(")
_COMPOUND_CHARS = re.compile(r"[\w\-.#:*&\\%|]")
_ANCHOR_TYPE = re.compile(r"(body|html|:root)(?![\w-])")
_ANCHOR_ID = re.compile(r"#(?:terminal-grid|app)(?![\w-])")
_ANCHOR_IN_IS = re.compile(r":(?:is|where|matches)\((?:[^()]*,)?\s*(?:body|html|:root)(?![\w-])")


def _match_back(text: str, close: int, opener: str, closer: str) -> int:
    depth = 0
    for i in range(close, -1, -1):
        if text[i] == closer:
            depth += 1
        elif text[i] == opener:
            depth -= 1
            if depth == 0:
                return i
    return 0


def _compound_start(text: str, has_at: int) -> int:
    j = has_at
    while j > 0:
        c = text[j - 1]
        if c == ")":
            j = _match_back(text, j - 1, "(", ")")
        elif c == "]":
            j = _match_back(text, j - 1, "[", "]")
        elif c == "(":
            name = re.search(r":[\w-]+$", text[: j - 1])
            if name is None or not text.startswith(_WRAPPERS, name.start()):
                break
            j = name.start()
        elif _COMPOUND_CHARS.match(c):
            j -= 1
        else:
            break
    return j


def _unwrap(compound: str) -> str:
    c = compound.strip()
    while c.count("(") > c.count(")"):
        opener = next((w for w in _WRAPPERS if c.startswith(w)), None)
        if opener is None:
            break
        c = c[len(opener):].strip()
    return c


def _starts_selector(text: str, j: int) -> bool:
    k = j
    while k > 0 and text[k - 1].isspace():
        k -= 1
    return k == 0 or text[k - 1] in "{};,"


def _subject(selector: str) -> str:
    depth = 0
    cut = 0
    for i, ch in enumerate(selector):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif depth == 0 and (ch.isspace() or ch in ">+~"):
            cut = i + 1
    return selector[cut:].strip()


def _enclosing_selector(text: str, j: int) -> str | None:
    depth = 0
    i = j
    while i > 0:
        i -= 1
        if text[i] == "}":
            depth += 1
        elif text[i] == "{":
            if depth:
                depth -= 1
                continue
            start = max(text.rfind("{", 0, i), text.rfind("}", 0, i), text.rfind(";", 0, i)) + 1
            head = text[start:i].strip()
            if head.startswith("@"):
                return _enclosing_selector(text, start)
            return head
    return None


def _compound_page_wide(text: str, compound: str, j: int) -> bool:
    c = _unwrap(compound)
    flat = c
    while re.search(r"\([^()]*\)", flat):
        flat = re.sub(r"\([^()]*\)", "\u00a7", flat)
    if _ANCHOR_TYPE.match(c) or _ANCHOR_ID.search(flat) or _ANCHOR_IN_IS.search(c):
        return True
    if c.startswith("&"):
        outer = _enclosing_selector(text, j)
        return outer is not None and any(_compound_page_wide(text, _subject(part), j) for part in outer.split(","))
    bare = re.sub(r":{1,2}[\w-]+", "", flat).replace("\u00a7", "").strip()
    return bare in ("", "*") and _starts_selector(text, j)


def page_wide_has(css: str) -> list[str]:
    text = _COMMENT.sub("", css).lower()
    hits = []
    for m in re.finditer(r":has\(", text):
        j = _compound_start(text, m.start())
        if _compound_page_wide(text, text[j:m.start()], j):
            hits.append((text[j:m.end()]).strip())
    return hits


def scan(root: Path) -> dict[str, int]:
    found: dict[str, int] = {}
    for rel in SCAN_ROOTS:
        for path in sorted((root / rel).rglob("*")):
            if path.suffix not in (".css", ".svelte") or "node_modules" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".svelte":
                text = "\n".join(_STYLE_BLOCK.findall(text))
            hits = page_wide_has(text)
            if hits:
                found[path.relative_to(root).as_posix()] = len(hits)
    return found


BAD_SHAPES = {
    "body": "body:has(#terminal-screen.active) #x { }",
    "html over body": "html:has(body.modal-stack-locked) { }",
    "grid id": "#terminal-grid:has(> .oc-surface) > .a { }",
    "body with class": "body.menu-page-open:has([data-page-back]) #bar { }",
    "html with attributes": "html[data-popout][data-desktop-chrome]:has(.oc-topbar) body { }",
    "not around has": "body:not(:has(.session-sidebar-panel--open)) .w { }",
    "svelte global": ":global(body:has(.x)) .w { }",
    "selector list": "a, body:has(.x) { }",
    "bare has": ":has(.x) .y { }",
    "star has": "*:has(.x) { }",
    "root": ":root:has(.x) { }",
    "is wrapper": ":is(body):has(.x) .y { }",
    "where wrapper": ":where(body):has(.x) .y { }",
    "is list": ":is(.a, html):has(.x) .y { }",
    "nested ampersand": "body { &:has(.x) { color: red } }",
    "nested ampersand class": "body { &.a:has(.x) { color: red } }",
    "nested in at-rule": "@media (min-width: 1px) { html { &:has(.x) { color: red } } }",
    "body with id": "body#main:has(.x) { }",
    "pseudo-class": "html:hover:has(.x) { }",
    "is(not) modifier": "body:is(:not(.a)):has(.x) { }",
    "uppercase": "BODY:has(.x) { }",
    "second has": "body:has(.a):has(.b) { }",
    "app id": "#app:has(.x) { }",
}

GOOD_SHAPES = {
    "local class": ".header--home:has(.controls--folded) { }",
    "child combinator argument": ".session-sidebar-group > .body:has(> *) { }",
    "local not": ".oc-chart-frame:not(:has(> .head:first-child)) { }",
    "where around attribute": ":where([data-btn]:not(:has(> [data-btn-label]))) { }",
    "comment only": "/* body:has(.x) is the old rule */ .a { }",
    "name that ends in body": ".nobody:has(.x) { }",
    "descendant of body": "body .row:has(.x) { }",
    "ampersand in local rule": ".card { &:has(.x) { color: red } }",
    "ampersand under body descendant": "body .card { &:has(.x) { color: red } }",
    "bare after ancestor": ".list :has(.x) { }",
    "body as argument only": ".row:has(body) { }",
}


@pytest.mark.parametrize("name", sorted(BAD_SHAPES))
def test_the_matcher_flags_each_page_wide_shape(name: str) -> None:
    assert page_wide_has(BAD_SHAPES[name]), BAD_SHAPES[name]


@pytest.mark.parametrize("name", sorted(GOOD_SHAPES))
def test_the_matcher_spares_local_subtrees(name: str) -> None:
    assert not page_wide_has(GOOD_SHAPES[name]), GOOD_SHAPES[name]


def test_no_stylesheet_anchors_has_on_a_page_wide_ancestor() -> None:
    found = scan(REPO_ROOT)
    new = {path: n for path, n in found.items() if KNOWN.get(path) != n}
    assert not new, (
        "page-wide :has() re-evaluates on every DOM insert (#1940). Use a page flag "
        f"(web/src/lib/page-flags/page-flags.ts) instead: {new}"
    )
    stale = sorted(path for path in KNOWN if path not in found)
    assert not stale, f"KNOWN lists files that no longer offend, delete the lines: {stale}"

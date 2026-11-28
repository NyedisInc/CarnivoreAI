from __future__ import annotations

import re

from tests.python.design_system._sources import REPO, strip_comments, top_level_chunks

FRAMES_CSS = REPO / "web" / "src" / "opscenter" / "page-frames.css"
PAGE_SVELTE = REPO / "web" / "src" / "opscenter" / "ui" / "Page.svelte"
PHONE_MEDIA = re.compile(r"@media\s*\(max-width:\s*767px\)\s*\{")
SELECTOR = ".oc-page__frame[data-scroll='self'] .oc-page__scroll"


def media_blocks(css: str, opener: re.Pattern[str]) -> list[str]:
    blocks: list[str] = []
    for match in opener.finditer(css):
        depth, start = 1, match.end()
        for index in range(start, len(css)):
            depth += {"{": 1, "}": -1}.get(css[index], 0)
            if depth == 0:
                blocks.append(css[start:index])
                break
    return blocks


def test_phone_scroller_inside_a_self_nav_frame_is_visible() -> None:
    blocks = media_blocks(strip_comments(FRAMES_CSS.read_text()), PHONE_MEDIA)
    assert blocks, "page-frames.css has no max-width: 767px block, so nothing was checked"
    rules = [
        body for block in blocks
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", block)
        if selector.strip() == SELECTOR
    ]
    assert rules, f"no phone rule on {SELECTOR!r}: a sticky row inside the page's scroller sticks to a box that never scrolls"
    assert any(re.search(r"overflow:\s*visible", body) for body in rules), f"{SELECTOR!r} below 768 must be overflow: visible"


def test_frame_draws_the_scroll_attribute() -> None:
    source = PAGE_SVELTE.read_text()
    assert re.search(r'class="oc-page__frame"[^>]*data-scroll=', source), "Page.svelte's nav frame lost data-scroll"


def test_embedded_page_rows_do_not_pin() -> None:
    tools = REPO / "web" / "src" / "opscenter" / "page-tools.css"
    unlayered = [c for c in top_level_chunks(strip_comments(tools.read_text())) if not c.startswith("@layer")]
    rule = next((c for c in unlayered if c.split("{", 1)[0].strip() == ".oc-page--embedded > .oc-page__away"), "")
    assert rule, "page-tools.css has no unlayered `.oc-page--embedded > .oc-page__away` rule"
    assert re.search(r"position:\s*static", rule) and re.search(r"transform:\s*none", rule), rule

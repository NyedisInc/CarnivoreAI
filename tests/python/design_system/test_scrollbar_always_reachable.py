from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SKIN = REPO / "client" / "css" / "scrollbars.css"
_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_LAYOUT_PROPS = re.compile(
    r"(?<![\w-])(overflow(?:-[xy])?|scrollbar-width|scrollbar-gutter"
    r"|width|height|min-width|min-height|border(?:-width)?|padding)\s*:"
)


def _strip(text: str) -> str:
    return _COMMENT.sub("", text)


def _rules(text: str) -> list[tuple[str, str]]:
    return [(m.group(1).strip(), m.group(2)) for m in _RULE.finditer(_strip(text))]


def _hover_layout_offenders(text: str) -> list[str]:
    bad = []
    for selector, body in _rules(text):
        if ":hover" not in selector and ":focus-within" not in selector:
            continue
        on_bar = "::-webkit-scrollbar" in selector
        for m in _LAYOUT_PROPS.finditer(body):
            prop = m.group(1)
            if on_bar or prop.startswith(("overflow", "scrollbar-")):
                bad.append(f"{selector} {{ {prop} }}")
    return bad


def test_shared_skin_exists_and_thumb_is_drawn_at_rest() -> None:
    css = _strip(SKIN.read_text(encoding="utf-8"))
    rest = dict(_rules(css)).get("::-webkit-scrollbar-thumb")
    assert rest, "the shared ::-webkit-scrollbar-thumb rule is missing"
    assert "var(--oc-scrollbar-thumb-rest)" in rest
    assert not re.search(r"(?:^|[\s,])(?::hover|:focus-within)::-webkit-scrollbar", css), (
        "the bar must not be revealed through its scroller's :hover / :focus-within"
    )


def test_no_rule_toggles_scrollbar_size_or_overflow_on_hover() -> None:
    sources = list((REPO / "client" / "css").glob("*.css"))
    sources += list((REPO / "web" / "src").rglob("*.css"))
    sources += list((REPO / "web" / "src").rglob("*.svelte"))
    offenders = []
    for path in sources:
        for hit in _hover_layout_offenders(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(REPO)}: {hit}")
    assert not offenders, offenders


def test_thumb_geometry_is_identical_at_rest_and_on_hover() -> None:
    rules = dict(_rules(SKIN.read_text(encoding="utf-8")))
    for state in (
        "::-webkit-scrollbar-thumb:hover",
        "::-webkit-scrollbar-thumb:active",
        "::-webkit-scrollbar-track:hover",
    ):
        props = re.findall(r"([\w-]+)\s*:", rules[state])
        assert props == ["background-color"], (state, props)


def test_negative_controls_go_red() -> None:
    assert _hover_layout_offenders(".a:hover::-webkit-scrollbar { width: 4px; }")
    assert _hover_layout_offenders(".a:hover { overflow: auto; }")
    assert not _hover_layout_offenders(".a:hover { width: 4px; }")

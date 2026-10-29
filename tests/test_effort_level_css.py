
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

REPO = Path(__file__).resolve().parent.parent
CSS = (REPO / "client" / "css" / "effort-level.css").read_text(encoding="utf-8")
TOKENS = (REPO / "web" / "src" / "opscenter" / "tokens.css").read_text(encoding="utf-8")

LEVELS = ("low", "medium", "high", "xhigh", "max", "ultracode")
MOVING = {"xhigh", "max", "ultracode"}
COLOURS = {
    "low": "--oc-yellow",
    "medium": "--oc-green",
    "high": "--oc-cyan",
    "xhigh": "--oc-purple-light",
    "max": "--oc-coral",
    "ultracode": "--oc-purple-deep",
}


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _split_reduced(text: str):
    body = _strip_comments(text)
    start = body.index("@media (prefers-reduced-motion: reduce)")
    return body[:start], body[start:]


def _level_rules(text: str) -> Dict[str, str]:
    rules: Dict[str, str] = {}
    for level in LEVELS:
        match = re.search(
            r"\.effort-level\.effort--" + level
            + (r":not\(\.session-sidebar-row-model\)" if level == "high" else "")
            + r"\s*\{([^}]*)\}", text
        )
        assert match, "no rule for " + level
        rules[level] = match.group(1)
    return rules


def test_each_level_wears_its_own_token_colour():
    outside, _ = _split_reduced(CSS)
    rules = _level_rules(outside)
    assert len(rules) == len(LEVELS)
    for level, token in COLOURS.items():
        assert "color: var(" + token + ")" in rules[level], level


def test_only_xhigh_max_and_ultracode_move():
    outside, _ = _split_reduced(CSS)
    rules = _level_rules(outside)
    moving = {level for level, body in rules.items() if "animation:" in body}
    if re.search(r"\.effort--max::before[^{]*\{[^}]*animation:", outside):
        moving.add("max")
    assert moving == MOVING


def test_only_ultracode_has_sparkles():
    outside, _ = _split_reduced(CSS)
    sparkle_rules = re.findall(r"([^{}]*)\{[^}]*animation:\s*effort-twinkle", outside)
    assert sparkle_rules, "the twinkle rule exists"
    owners = set(re.findall(r"\.effort--(\w+)::(?:before|after)", " ".join(sparkle_rules)))
    assert owners == {"ultracode"}


def test_reduced_motion_stops_every_animation_and_sparkle():
    _, inside = _split_reduced(CSS)
    stopped = set(re.findall(r"\.effort-level\.effort--(\w+)\s*[,{]", inside))
    assert stopped >= MOVING, "every moving level is named inside the block"
    assert "animation: none" in inside
    assert re.search(r"::after\s*\{\s*content:\s*none", inside), "sparkles removed"
    assert "color" not in inside, "reduced motion keeps the colours"


def test_no_literal_colour_in_the_stylesheet():
    body = _strip_comments(CSS)
    assert "var(--oc-" in body
    masks = re.findall(r"(?<![\w-])(?:-webkit-)?mask:\s*([^;]+);", body)
    assert masks and all("--effort-robot-mask" in value for value in masks)
    painted = re.sub(r"--effort-robot-mask:\s*url\([^;]+;", "", body)
    painted = re.sub(r"rgb\(from ", "relative(", painted)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", painted)


def test_the_purples_are_derived_from_the_theme_text_colour():
    for name in ("--oc-purple-light", "--oc-purple-deep"):
        derived = re.search(re.escape(name) + r":\s*oklch\(from var\(--color-fg", TOKENS)
        assert derived, name + " must derive from the manifest's --color-fg"
        assert re.search(
            r"@supports not \(color: oklch\(from red l c h\)\)[^@]*" + re.escape(name), TOKENS
        ), name + " needs a fallback where relative colour is unsupported"

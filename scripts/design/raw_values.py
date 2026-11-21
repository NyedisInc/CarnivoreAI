from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from scripts.design.css_color_names import NAMED_COLORS
from scripts.design.harness_paths import is_harness

REPO = Path(__file__).resolve().parents[2]
WEB_SRC = REPO / "web" / "src"
SERVER_CPLUGS = REPO / "src" / "plugins"
SCAN_ROOTS: tuple[tuple[Path, frozenset[str]], ...] = (
    (WEB_SRC, frozenset({".css", ".svelte"})),
    (SERVER_CPLUGS, frozenset({".css", ".html"})),
)
BASELINE = REPO / "tests" / "fixtures" / "design_raw_values_baseline.json"
SHAPE_AND_MOTION_KINDS = ("radius", "line-height", "tracking", "z-index", "duration", "weight", "border-width")
LITERAL_KINDS = ("fallback", "color-def", "inline")
KINDS = ("spacing", "font", "color", *SHAPE_AND_MOTION_KINDS, *LITERAL_KINDS)
EXEMPT = (
    "web/src/opscenter/tokens.css",
    "web/src/lib/elite/",
)

_COMMENTS = re.compile(r"/\*.*?\*/", re.S)
_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
_MARKUP_SKIP = re.compile(r"<(style|script)[^>]*>.*?</\1>|<!--.*?-->", re.S)
_STYLE_ATTR = re.compile(r"""(?<![\w:-])style\s*=\s*(["'])(.*?)\1""", re.S)
_EXPRESSION = re.compile(r"\{[^{}]*\}")
_STRING = re.compile(r""""[^"]*"|'[^']*'""")
_VAR_OPEN = re.compile(r"\bvar\(")
_ANY_NUMBER = re.compile(r"(?<![\w.#])-?(\d*\.?\d+)")
_DECL = re.compile(r"(?<![\w-])(-{0,2}[a-zA-Z_][a-zA-Z0-9_-]*)\s*:\s*([^;{}]+)")
_URL = re.compile(r"url\([^)]*\)")
_INNER_VAR = re.compile(r"var\([^()]*\)")
_SPACING_PROP = re.compile(r"^(?:padding|margin)(?:-[a-z-]+)?$|^(?:row-|column-)?gap$")
_LENGTH = re.compile(r"(?<![\w.#-])(\d*\.?\d+)(px|rem|em)\b")
_FONT_LENGTH = re.compile(r"(?<![\w.#-])\d*\.?\d+(?:px|rem|em|pt)\b")
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_COLOR_FN = re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\((?!\s*from\b)")
_COLOR_PROP = re.compile(
    r"^(?:color|background(?:-color)?|border(?:-[a-z]+)*-color|border(?:-(?:top|right|bottom|left))?|outline(?:-color)?"
    r"|fill|stroke|box-shadow|text-shadow|caret-color|accent-color|text-decoration-color|column-rule-color)$"
)
_RADIUS_PROP = re.compile(r"^border(?:-(?:top|bottom|start|end)-(?:left|right|start|end))?-radius$")
_RADIUS_LENGTH = re.compile(r"(?<![\w.#-])(\d*\.?\d+)(?:px|rem|em|%)(?![\w-])")
_NUMBER = re.compile(r"(?<![\w.#-])\d*\.?\d+")
_INTEGER = re.compile(r"(?<![\w.#-])-?(\d+)(?![\w.])")
_MOTION_PROP = re.compile(r"^(?:transition|animation)(?:-(?:duration|delay))?$")
_TIME = re.compile(r"(?<![\w.#-])(\d*\.?\d+)(ms|s)\b")
_WEIGHT = re.compile(r"(?<![\w.#-])(?:\d+|bold|bolder|lighter)(?![\w-])")
_BORDER_WIDTH_PROP = re.compile(
    r"^(?:border(?:-(?:top|right|bottom|left|block|inline)(?:-(?:start|end))?)?|outline)(?:-width)?$"
)
_NAMED = re.compile(r"(?<![\w-])(?:" + "|".join(sorted(NAMED_COLORS, key=len, reverse=True)) + r")(?![\w-])")


def strip_vars(value: str) -> str:
    value = _URL.sub("", value)
    previous = None
    while previous != value:
        previous = value
        value = _INNER_VAR.sub("", value)
    return value


def var_fallbacks(value: str) -> list[str]:
    out: list[str] = []
    for match in _VAR_OPEN.finditer(value):
        depth, comma, end = 1, -1, match.end()
        while end < len(value) and depth:
            char = value[end]
            depth += (char == "(") - (char == ")")
            if char == "," and depth == 1 and comma < 0:
                comma = end
            end += 1
        if comma >= 0:
            out.append(value[comma + 1:end - 1])
    return out


def _is_color(bare: str) -> bool:
    return bool(_HEX.search(bare) or _COLOR_FN.search(bare) or _NAMED.search(bare.lower()))


def _has_literal(fallback: str) -> bool:
    bare = strip_vars(fallback)
    return _is_color(bare) or any(float(n) != 0 for n in _ANY_NUMBER.findall(bare))


def css_text(path: Path, suffixes: frozenset[str] = frozenset({".css", ".svelte"})) -> str:
    if path.suffix not in suffixes:
        return ""
    text = path.read_text(encoding="utf-8")
    if path.suffix != ".css":
        text = "".join(_STYLE.findall(text))
    return _COMMENTS.sub("", text)


def inline_count(path: Path) -> int:
    if path.suffix != ".svelte":
        return 0
    markup = _MARKUP_SKIP.sub("", path.read_text(encoding="utf-8"))
    count = 0
    for _quote, attr in _STYLE_ATTR.findall(markup):
        bare = _EXPRESSION.sub("", attr)
        count += sum(1 for prop, value in _DECL.findall(bare) if classify(prop.lower(), value))
    return count


def classify(prop: str, value: str) -> list[str]:
    kinds: list[str] = ["fallback"] if any(_has_literal(f) for f in var_fallbacks(value)) else []
    bare = strip_vars(value)
    if prop.startswith("--"):
        return [*kinds, "color-def"] if _is_color(_STRING.sub("", bare)) else kinds
    if _SPACING_PROP.match(prop) and any(float(n) != 0 for n, _unit in _LENGTH.findall(bare)):
        kinds.append("spacing")
    if prop == "font-size" and _FONT_LENGTH.search(bare):
        kinds.append("font")
    if _HEX.search(bare) or _COLOR_FN.search(bare) or (_COLOR_PROP.match(prop) and _NAMED.search(bare.lower())):
        kinds.append("color")
    kinds.extend(_shape_and_motion_kinds(prop, bare))
    return kinds


def _nonzero(numbers: list[str]) -> bool:
    return any(float(n) != 0 for n in numbers)


def _shape_and_motion_kinds(prop: str, bare: str) -> list[str]:
    rules = (
        ("radius", _RADIUS_PROP.match(prop) is not None and _nonzero(_RADIUS_LENGTH.findall(bare))),
        ("line-height", prop == "line-height" and _NUMBER.search(bare) is not None),
        ("tracking", prop == "letter-spacing" and _nonzero([n for n, _unit in _LENGTH.findall(bare)])),
        ("z-index", prop == "z-index" and _nonzero(_INTEGER.findall(bare))),
        ("duration", _MOTION_PROP.match(prop) is not None and _nonzero([n for n, _unit in _TIME.findall(bare)])),
        ("weight", prop == "font-weight" and _WEIGHT.search(bare.lower()) is not None),
        ("border-width", _BORDER_WIDTH_PROP.match(prop) is not None and _nonzero([n for n, _unit in _LENGTH.findall(bare)])),
    )
    return [kind for kind, hit in rules if hit]


def count_css(css: str) -> dict[str, int]:
    counts = dict.fromkeys(KINDS, 0)
    for prop, value in _DECL.findall(css):
        for kind in classify(prop.lower(), value):
            counts[kind] += 1
    return counts


def is_exempt(rel: str) -> bool:
    return is_harness(rel) or any(rel == e or (e.endswith("/") and rel.startswith(e)) for e in EXEMPT)


def scan(root: Path = WEB_SRC, base: Path = REPO, suffixes: frozenset[str] = frozenset({".css", ".svelte"})) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "node_modules" in path.parts:
            continue
        rel = path.relative_to(base).as_posix()
        if is_exempt(rel):
            continue
        counts = {**count_css(css_text(path, suffixes)), "inline": inline_count(path)}
        counts = {k: v for k, v in counts.items() if v}
        if counts:
            out[rel] = counts
    return out


def scan_repo(roots: tuple[tuple[Path, frozenset[str]], ...] = SCAN_ROOTS, base: Path = REPO) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for root, suffixes in roots:
        if not root.is_dir():
            raise FileNotFoundError(f"{root} does not exist")
        out.update(scan(root, base, suffixes))
    return out


def load_baseline() -> dict[str, dict[str, int]]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))["files"]


def compare(
    found: dict[str, dict[str, int]], baseline: dict[str, dict[str, int]], kinds: tuple[str, ...] = KINDS,
) -> tuple[list[str], list[str]]:
    grown: list[str] = []
    stale: list[str] = []
    for rel in sorted(set(found) | set(baseline)):
        for kind in kinds:
            have = found.get(rel, {}).get(kind, 0)
            allowed = baseline.get(rel, {}).get(kind, 0)
            if have > allowed:
                grown.append(f"{rel} {kind}: {have} > {allowed}")
            elif have < allowed:
                stale.append(f"{rel} {kind}: {have} < {allowed}")
    return grown, stale


def write_baseline(found: dict[str, dict[str, int]]) -> None:
    totals = {k: sum(c.get(k, 0) for c in found.values()) for k in KINDS}
    doc = {
        "about": "raw value declarations per web/src and src/plugins file and kind (scripts/design/raw_values.py KINDS); "
                 "may only fall "
                 "(scripts/design/raw_values.py, issue #2033 guard G1)",
        "totals": totals,
        "files": found,
    }
    BASELINE.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    found = scan_repo()
    if "--write" in argv:
        write_baseline(found)
    totals = {k: sum(c.get(k, 0) for c in found.values()) for k in KINDS}
    print(f"files with raw values: {len(found)}; totals {totals}")
    grown, stale = compare(found, load_baseline())
    for line in grown:
        print("GREW  " + line)
    for line in stale:
        print("LOWER " + line)
    return 1 if grown else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

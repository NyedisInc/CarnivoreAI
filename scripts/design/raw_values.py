from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEB_SRC = REPO / "web" / "src"
BASELINE = REPO / "tests" / "fixtures" / "design_raw_values_baseline.json"
KINDS = ("spacing", "font", "color")
EXEMPT = (
    "web/src/opscenter/tokens.css",
    "web/src/lib/elite/",
)

_COMMENTS = re.compile(r"/\*.*?\*/", re.S)
_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
_DECL = re.compile(r"(?<![\w-])([a-z-]+)\s*:\s*([^;{}]+)")
_URL = re.compile(r"url\([^)]*\)")
_INNER_VAR = re.compile(r"var\([^()]*\)")
_SPACING_PROP = re.compile(r"^(?:padding|margin)(?:-[a-z-]+)?$|^(?:row-|column-)?gap$")
_LENGTH = re.compile(r"(?<![\w.#-])(\d*\.?\d+)(px|rem|em)\b")
_FONT_LENGTH = re.compile(r"(?<![\w.#-])\d*\.?\d+(?:px|rem|em|pt)\b")
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_COLOR_FN = re.compile(r"\b(?:rgba?|hsla?)\((?!\s*from\b)")
_COLOR_PROP = re.compile(
    r"^(?:color|background(?:-color)?|border(?:-[a-z]+)*-color|border(?:-(?:top|right|bottom|left))?|outline(?:-color)?"
    r"|fill|stroke|box-shadow|text-shadow|caret-color|accent-color|text-decoration-color|column-rule-color)$"
)
_NAMED = re.compile(
    r"(?<![\w-])(?:white|black|red|green|blue|yellow|orange|purple|pink|gray|grey|silver|maroon|navy|teal|olive|lime"
    r"|aqua|fuchsia|cyan|magenta|gold|brown)(?![\w-])"
)


def strip_vars(value: str) -> str:
    value = _URL.sub("", value)
    previous = None
    while previous != value:
        previous = value
        value = _INNER_VAR.sub("", value)
    return value


def css_text(path: Path) -> str:
    if path.suffix not in {".css", ".svelte"}:
        return ""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".svelte":
        text = "".join(_STYLE.findall(text))
    return _COMMENTS.sub("", text)


def classify(prop: str, value: str) -> list[str]:
    if prop.startswith("--"):
        return []
    bare = strip_vars(value)
    kinds: list[str] = []
    if _SPACING_PROP.match(prop) and any(float(n) != 0 for n, _unit in _LENGTH.findall(bare)):
        kinds.append("spacing")
    if prop == "font-size" and _FONT_LENGTH.search(bare):
        kinds.append("font")
    if _HEX.search(bare) or _COLOR_FN.search(bare) or (_COLOR_PROP.match(prop) and _NAMED.search(bare.lower())):
        kinds.append("color")
    return kinds


def count_css(css: str) -> dict[str, int]:
    counts = dict.fromkeys(KINDS, 0)
    for prop, value in _DECL.findall(css):
        for kind in classify(prop.lower(), value):
            counts[kind] += 1
    return counts


def is_exempt(rel: str) -> bool:
    return any(rel == e or (e.endswith("/") and rel.startswith(e)) for e in EXEMPT)


def scan(root: Path = WEB_SRC, base: Path = REPO) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "node_modules" in path.parts:
            continue
        rel = path.relative_to(base).as_posix()
        if is_exempt(rel):
            continue
        counts = {k: v for k, v in count_css(css_text(path)).items() if v}
        if counts:
            out[rel] = counts
    return out


def load_baseline() -> dict[str, dict[str, int]]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))["files"]


def compare(found: dict[str, dict[str, int]], baseline: dict[str, dict[str, int]]) -> tuple[list[str], list[str]]:
    grown: list[str] = []
    stale: list[str] = []
    for rel in sorted(set(found) | set(baseline)):
        for kind in KINDS:
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
        "about": "raw spacing/font-size/color declarations per web/src file; may only fall "
                 "(scripts/design/raw_values.py, issue #2033 guard G1)",
        "totals": totals,
        "files": found,
    }
    BASELINE.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    found = scan()
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

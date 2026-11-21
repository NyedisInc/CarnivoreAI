from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from scripts.design import raw_values
from scripts.design.harness_paths import is_harness

REPO = raw_values.REPO
CLIENT_CSS = REPO / "client" / "css"
SCAN_ROOTS: tuple[tuple[Path, frozenset[str]], ...] = (*raw_values.SCAN_ROOTS, (CLIENT_CSS, frozenset({".css"})))
OWNERS: tuple[str, ...] = ("web/src/lib/base/", "web/src/opscenter/controls.css", "web/src/opscenter/fields.css")
BASELINE = REPO / "tests" / "fixtures" / "design_reach_ins_baseline.json"
KINDS: tuple[str, ...] = ("hook", "global", "private-write", "important")

_HOOK = re.compile(r"\[data-(?:btn|field)(?![\w-])|\.(?:oc-btn|oc-ibtn|oc-field|oc-pick|modal-btn)(?![a-zA-Z0-9])")
_GLOBAL_OC = re.compile(r":global\(\s*\.oc-")
_PRIVATE_WRITE = re.compile(r"(?<![\w-])--_(?:btn|field|pick)-[\w-]*\s*:")
_IMPORTANT = re.compile(r"!\s*important\b", re.I)


def split_top_level(text: str, sep: str) -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    for ch in text:
        depth += (ch in "([") - (ch in ")]")
        if ch == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur).strip())
    return [p for p in parts if p]


def style_preludes(css: str) -> list[str]:
    out: list[str] = []
    stack: list[bool] = []
    start = 0
    for i, ch in enumerate(css):
        if ch == "{":
            prelude = css[start:i].strip()
            if prelude and not prelude.startswith("@") and not any(stack):
                out.append(prelude)
            stack.append(not prelude.startswith("@"))
            start = i + 1
        elif ch == "}":
            if stack:
                stack.pop()
            start = i + 1
        elif ch == ";" and not any(stack):
            start = i + 1
    return out


def count_css(css: str) -> dict[str, int]:
    counts = dict.fromkeys(KINDS, 0)
    for prelude in style_preludes(css):
        for selector in split_top_level(prelude, ","):
            counts["hook"] += 1 if _HOOK.search(selector) else 0
            counts["global"] += len(_GLOBAL_OC.findall(selector))
    counts["private-write"] = len(_PRIVATE_WRITE.findall(css))
    counts["important"] = len(_IMPORTANT.findall(css))
    return counts


def is_owner(rel: str) -> bool:
    return is_harness(rel) or any(rel == o or (o.endswith("/") and rel.startswith(o)) for o in OWNERS)


def scan(roots: tuple[tuple[Path, frozenset[str]], ...] = SCAN_ROOTS, base: Path = REPO) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for root, suffixes in roots:
        if not root.is_dir():
            raise FileNotFoundError(f"{root} does not exist")
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "node_modules" in path.parts:
                continue
            rel = path.relative_to(base).as_posix()
            if is_owner(rel):
                continue
            counts = {k: v for k, v in count_css(raw_values.css_text(path, suffixes)).items() if v}
            if counts:
                out[rel] = counts
    return out


def load_baseline() -> dict[str, dict[str, int]]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))["files"]


def write_baseline(found: dict[str, dict[str, int]]) -> None:
    doc = {
        "about": "reach-ins into the shared base controls per file and kind (scripts/design/reach_ins.py KINDS, "
                 "top-down review M7); may only fall",
        "totals": {k: sum(c.get(k, 0) for c in found.values()) for k in KINDS},
        "files": found,
    }
    BASELINE.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    found = scan()
    if "--write" in argv:
        write_baseline(found)
    totals = {k: sum(c.get(k, 0) for c in found.values()) for k in KINDS}
    print(f"files with reach-ins: {len(found)}; totals {totals}")
    grown, stale = raw_values.compare(found, load_baseline(), KINDS)
    for line in grown:
        print("GREW  " + line)
    for line in stale:
        print("LOWER " + line)
    return 1 if grown else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

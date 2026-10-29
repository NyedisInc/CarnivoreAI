from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOTS = (REPO / "client" / "css", REPO / "web" / "src")
BASELINE = REPO / "tests" / "fixtures" / "infinite_animations_baseline.json"

_COMMENTS = re.compile(r"/\*.*?\*/", re.S)
_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
_DECL = re.compile(r"(?<![\w-])(animation|animation-iteration-count)\s*:\s*([^;{}]+)")
_INFINITE = re.compile(r"(?<![\w-])infinite(?![\w-])")


def css_text(path: Path) -> str:
    if path.suffix not in {".css", ".svelte"}:
        return ""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".svelte":
        text = "".join(_STYLE.findall(text))
    return _COMMENTS.sub("", text)


def count_css(css: str) -> int:
    return sum(1 for _prop, value in _DECL.findall(css) if _INFINITE.search(value))


def scan(roots: tuple[Path, ...] = ROOTS, base: Path = REPO) -> dict[str, int]:
    out: dict[str, int] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "node_modules" in path.parts:
                continue
            n = count_css(css_text(path))
            if n:
                out[path.relative_to(base).as_posix()] = n
    return out


def load_baseline() -> dict[str, int]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))["files"]


def compare(found: dict[str, int], baseline: dict[str, int]) -> tuple[list[str], list[str]]:
    grown: list[str] = []
    stale: list[str] = []
    for rel in sorted(set(found) | set(baseline)):
        have, allowed = found.get(rel, 0), baseline.get(rel, 0)
        if have > allowed:
            grown.append(f"{rel}: {have} > {allowed}")
        elif have < allowed:
            stale.append(f"{rel}: {have} < {allowed}")
    return grown, stale


def write_baseline(found: dict[str, int]) -> None:
    doc = {
        "about": "infinite CSS animations per client/css + web/src file; may only fall "
                 "(scripts/design/infinite_animations.py, calm round 4 card A8b)",
        "total": sum(found.values()),
        "files": found,
    }
    BASELINE.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    found = scan()
    if "--write" in argv:
        write_baseline(found)
    print(f"files with infinite animations: {len(found)}; total {sum(found.values())}")
    grown, stale = compare(found, load_baseline())
    for line in grown:
        print("GREW  " + line)
    for line in stale:
        print("LOWER " + line)
    return 1 if grown else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

from __future__ import annotations

import re
import sys
from pathlib import Path

from scripts.design.harness_paths import is_harness
from tests.python.design_system._sources import REPO, css_of, split_selectors

ROOTS = ("web/src", "client/css", "client/style-guide", "cplugs")
ALLOWED_FILES = frozenset({
    "web/src/opscenter/page.css", "web/src/opscenter/page-frames.css", "web/src/opscenter/page-pair.css", "web/src/opscenter/ui/Page.svelte",
})
ALLOWED_PREFIXES = ("web/src/style-guide/", "client/style-guide/")

_REGION = re.compile(
    r"\.oc-titlebar(?![A-Za-z0-9])"
    r"|\.oc-page__(?:tabs|bar|away|body|scroll|main|side|detail|foot|notes|frame|col|fill|picker)(?![A-Za-z0-9])"
    r"|\.oc-page--[A-Za-z0-9]"
    r"|\[data-frame(?:-region)?(?![A-Za-z0-9-])"
    r"|\[data-pair(?![A-Za-z0-9-])"
)
_ELEMENT = re.compile(r"(?<![\w.#\[:(-])(?:header|aside)(?![\w-])")
_ATTRIBUTE = re.compile(r"\[[^\]]*\]")


class ScanError(Exception):
    pass


def preludes(css: str) -> list[str]:
    out: list[str] = []
    start = 0
    for i, ch in enumerate(css):
        if ch in "{};":
            if ch == "{":
                head = css[start:i].strip()
                if head and not head.startswith("@"):
                    out.append(head)
            start = i + 1
    return out


def names_region(selector: str) -> bool:
    return bool(_REGION.search(selector) or _ELEMENT.search(_ATTRIBUTE.sub("[]", selector)))


def region_selectors(css: str) -> list[str]:
    return [sel for head in preludes(css) for sel in split_selectors(head) if names_region(sel)]


def is_allowed(rel: str) -> bool:
    return rel in ALLOWED_FILES or rel.startswith(ALLOWED_PREFIXES)


def scan(repo: Path = REPO) -> dict[str, list[str]]:
    return scan_counted(repo)[0]


def scan_counted(repo: Path = REPO) -> tuple[dict[str, list[str]], int]:
    found: dict[str, list[str]] = {}
    seen = 0
    for root in ROOTS:
        base = repo / root
        if not base.is_dir():
            if root == "web/src":
                raise ScanError(f"scan root {base} does not exist")
            continue
        for path in sorted(p for suffix in ("*.css", "*.svelte") for p in base.rglob(suffix)):
            rel = path.relative_to(repo).as_posix()
            if "node_modules" in rel or is_harness(rel):
                continue
            css = css_of(path)
            if not css:
                continue
            seen += 1
            if is_allowed(rel):
                continue
            if sels := region_selectors(css):
                found[rel] = sels
    if not seen:
        raise ScanError("no stylesheet found to scan")
    return found, seen


def rows(found: dict[str, list[str]]) -> list[str]:
    out: list[str] = []
    for rel, sels in found.items():
        seen: dict[str, int] = {}
        for sel in sels:
            key = " ".join(sel.split())
            seen[key] = seen.get(key, 0) + 1
            out.append(f"{rel}::{key}" + (f"#{seen[key]}" if seen[key] > 1 else ""))
    return sorted(out)


def main(argv: list[str] | None = None) -> int:
    try:
        found = scan()
    except ScanError as exc:
        print(f"frame_regions: CANNOT RUN - {exc}", file=sys.stderr)
        return 2
    for rel, sels in sorted(found.items()):
        print(f"{rel}: {len(sels)}")
    print(f"total {sum(len(v) for v in found.values())} in {len(found)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())

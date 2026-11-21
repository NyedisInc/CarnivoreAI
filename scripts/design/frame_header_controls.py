from __future__ import annotations

import re
import sys
from pathlib import Path

from scripts.design import raw_controls as rc

REPO = rc.REPO
KEY_CHARS = 90
SNIPPET_NAMES = frozenset({"actions", "controls", "bar", "tabs", "find", "sub", "search"})
MANAGER_SNIPPET_NAMES = frozenset({"actions", "toolbar", "detailBar"})
HOSTS: dict[str, frozenset[str]] = {"Page": SNIPPET_NAMES, "ManagerFrame": MANAGER_SNIPPET_NAMES}

_HOST_OPEN = re.compile(r"<(Page|ManagerFrame)(?=\s)")
_SNIPPET_OPEN = re.compile(r"\{#snippet\s+(\w+)\s*\([^)]*\)\s*\}")
_SNIPPET_CLOSE = "{/snippet}"
_IMPORT = re.compile(r"""import\s+(\w+)\s+from\s+['"](\.[^'"]+\.svelte)['"]""")
_ANY_TAG = re.compile(r"<([A-Za-z][\w:.-]*)(?=[\s/>])")
_CLASS = re.compile(r"""\bclass\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_FAMILY = re.compile(r"(?<![\w-])(?:modal-btn|oc-btn)(?![A-Za-z0-9_])")


def snippet_bodies(clean: str) -> dict[str, list[tuple[int, int]]]:
    out: dict[str, list[tuple[int, int]]] = {}
    for m in _SNIPPET_OPEN.finditer(clean):
        depth, i = 1, m.end()
        while depth and i < len(clean):
            nxt_open = clean.find("{#snippet", i)
            nxt_close = clean.find(_SNIPPET_CLOSE, i)
            if nxt_close < 0:
                i = len(clean)
                break
            if 0 <= nxt_open < nxt_close:
                depth += 1
                i = nxt_open + 9
            else:
                depth -= 1
                i = nxt_close + len(_SNIPPET_CLOSE)
        out.setdefault(m.group(1), []).append((m.end(), i - len(_SNIPPET_CLOSE) if depth == 0 else len(clean)))
    return out


def brace_expression(text: str, open_at: int) -> str:
    depth = 0
    for i in range(open_at, len(text)):
        depth += (text[i] == "{") - (text[i] == "}")
        if depth == 0:
            return text[open_at + 1:i]
    return text[open_at + 1:]


def header_snippet_spans(clean: str) -> list[tuple[int, int]]:
    hosts = [(m, HOSTS[m.group(1)]) for m in _HOST_OPEN.finditer(clean)]
    if not hosts:
        return []
    bodies = snippet_bodies(clean)
    wanted: set[str] = set()
    for m, names in hosts:
        wanted.update(names)
        prop_re = re.compile(r"\b(?:" + "|".join(sorted(names)) + r")\s*=\s*\{")
        tag = clean[m.start():rc.tag_end(clean, m.start())]
        for prop in prop_re.finditer(tag):
            wanted.update(set(re.findall(r"[A-Za-z_]\w*", brace_expression(tag, prop.end() - 1))) & bodies.keys())
    return [span for name in sorted(wanted) for span in bodies.get(name, [])]


def offenders(clean: str, start: int = 0, end: int | None = None) -> list[tuple[int, str]]:
    stop = len(clean) if end is None else end
    found: list[tuple[int, str]] = []
    for m in _ANY_TAG.finditer(clean, start, stop):
        tag = clean[m.start():rc.tag_end(clean, m.start())]
        found_class = _CLASS.search(tag)
        klass = " ".join(g for g in found_class.groups() if g) if found_class else ""
        raw_button = m.group(1) in {"button", "input", "svelte:element"} and rc.classify(m.group(1), tag) == "buttons"
        if raw_button or _FAMILY.search(klass):
            found.append((clean.count("\n", 0, m.start()) + 1, " ".join(tag.split())[:KEY_CHARS]))
    return found


def drawn_components(source: str, clean: str, spans: list[tuple[int, int]], here: Path) -> list[Path]:
    imports = dict(_IMPORT.findall(source))
    names = {m.group(1) for s, e in spans for m in _ANY_TAG.finditer(clean, s, e)}
    return [p for name in sorted(names & imports.keys()) if (p := (here.parent / imports[name]).resolve()).is_file()]


def scan(root: Path = rc.WEB_SRC, base: Path = REPO) -> dict[str, list[tuple[int, str]]]:
    return scan_counted(root, base)[0]


def scan_counted(root: Path = rc.WEB_SRC, base: Path = REPO) -> tuple[dict[str, list[tuple[int, str]]], int]:
    if not root.is_dir():
        raise rc.ScanError(f"scan root {root} does not exist")
    found: dict[str, set[tuple[int, str]]] = {}
    pages = 0
    for path in sorted(root.rglob("*.svelte")):
        if not rc.is_scanned(path.relative_to(base).as_posix()):
            continue
        source = path.read_text(encoding="utf-8")
        clean = rc.blank_nonmarkup(source)
        spans = header_snippet_spans(clean)
        if not _HOST_OPEN.search(clean):
            continue
        pages += 1
        rel = path.relative_to(base).as_posix()
        for s, e in spans:
            found.setdefault(rel, set()).update(offenders(clean, s, e))
        for comp in drawn_components(source, clean, spans, path):
            crel = comp.relative_to(base).as_posix()
            if rc.is_scanned(crel):
                found.setdefault(crel, set()).update(offenders(rc.blank_nonmarkup(comp.read_text(encoding="utf-8"))))
    if not pages:
        raise rc.ScanError(f"no .svelte file under {root} draws a <Page")
    return {rel: sorted(items) for rel, items in sorted(found.items()) if items}, pages


def rows(found: dict[str, list[tuple[int, str]]]) -> list[str]:
    out: list[str] = []
    for rel, items in found.items():
        seen: dict[str, int] = {}
        for _line, key in items:
            seen[key] = seen.get(key, 0) + 1
            out.append(f"{rel}::{key}" + (f"#{seen[key]}" if seen[key] > 1 else ""))
    return sorted(out)


def main(argv: list[str] | None = None) -> int:
    try:
        found = scan()
    except rc.ScanError as exc:
        print(f"frame_header_controls: CANNOT RUN - {exc}", file=sys.stderr)
        return 2
    for rel, items in found.items():
        print(f"{rel}: lines {[line for line, _key in items]}")
    print(f"total {sum(len(v) for v in found.values())} in {len(found)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
